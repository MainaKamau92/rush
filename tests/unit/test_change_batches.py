from app.schemas.code_change import ChangeLine
from app.schemas.review import ReviewLimits
from app.services.change_batches import ChangeBatchService
from tests.unit.test_investigation import make_service, request, scope


def test_large_hunks_are_split_without_losing_changed_lines_or_anchors():
    original = scope()
    file = original.files[0]
    lines = tuple(
        ChangeLine(kind="added", new_line=i, text=f"result_{i} = {i}")
        for i in range(1, 201)
    )
    file = file.model_copy(
        update={
            "additions": 200,
            "deletions": 0,
            "hunks": (
                file.hunks[0].model_copy(update={"lines": lines, "new_lines": 200}),
            ),
        }
    )
    service = ChangeBatchService(
        ReviewLimits(batch_changes=True, changed_lines=25, source_bytes=8192)
    )
    admitted = service.prepare(original.model_copy(update={"files": (file,)}))
    batches = service.plan(admitted)
    assert len(batches) > 1 and admitted.complete
    delivered = [
        line
        for batch in batches
        for item in batch.files
        for hunk in item.hunks
        for line in hunk.lines
    ]
    assert delivered == list(lines)
    assert all(
        sum(f.additions + f.deletions for f in batch.files) <= 25 for batch in batches
    )
    assert len({h.id for f in admitted.files for h in f.hunks}) == sum(
        len(f.hunks) for f in admitted.files
    )
    assert all(admitted.anchor("customers.py", "RIGHT", i) for i in range(1, 201))


def test_an_oversized_line_is_a_named_real_omission():
    original = scope()
    file = original.files[0]
    huge = ChangeLine(kind="added", new_line=5, text="x" * 8192)
    hunk = file.hunks[0].model_copy(update={"lines": (*file.hunks[0].lines, huge)})
    original = original.model_copy(
        update={"files": (file.model_copy(update={"hunks": (hunk,)}),)}
    )
    result = ChangeBatchService(
        ReviewLimits(batch_changes=True, source_bytes=8192)
    ).prepare(original)
    assert not result.complete and result.limitations()
    assert result.omissions[0].new_path == "customers.py"
    assert not result.omissions[0].intentional
    assert result.anchor("customers.py", "RIGHT", 4)
    assert result.anchor("customers.py", "RIGHT", 5) is None


async def test_batch_question_names_are_isolated_but_read_identities_are_global():
    broker, _, reader, _ = make_service(ReviewLimits(batch_changes=True))
    original = reader.scope.files[0]
    second = original.hunks[0].model_copy(update={"id": "second-hunk"})
    reader.scope = reader.scope.model_copy(
        update={
            "files": (original.model_copy(update={"hunks": (*original.hunks, second)}),)
        }
    )
    admitted = (await broker.start("head", base="base")).scope
    ids = []
    for number, hunk in enumerate(admitted.files[0].hunks, 1):
        batch = admitted.model_copy(
            update={"files": (admitted.files[0].model_copy(update={"hunks": (hunk,)}),)}
        )
        broker.begin_batch(batch, f"batch-{number}:")
        item = request(origin_hunk_id=hunk.id)
        broker.open_question(item.question_id, item.question, item.origin_hunk_id)
        audit = await broker.read(item)
        assert audit.action == "read"
        ids.append(audit.snippet.id)
        broker.answer(
            item.question_id,
            "The helper returns the requested value.",
            (audit.snippet.id,),
        )
        view = broker.model_report()
        assert len(view.questions) == 1 and view.questions[0].id == "lookup"
        assert view.questions[0].answer
    report = broker.finish()
    assert [question.id for question in report.questions] == [
        "batch-1:lookup",
        "batch-2:lookup",
    ]
    assert len(set(ids)) == 2 and report.complete


def test_mode_only_changes_are_still_present_in_a_batch():
    original = scope()
    file = original.files[0].model_copy(
        update={"hunks": (), "additions": 0, "deletions": 0, "new_mode": "100755"}
    )
    result = ChangeBatchService(ReviewLimits(batch_changes=True)).plan(
        original.model_copy(update={"files": (file,)})
    )
    assert len(result) == 1 and result[0].files == (file,)


async def test_distinct_changed_origins_can_investigate_under_a_global_allowance():
    from dataclasses import replace

    broker, repository, reader, _ = make_service(
        ReviewLimits(batch_changes=True, changed_files=1, scoped_searches=2)
    )
    first = reader.scope.files[0]
    second = first.model_copy(
        update={
            "old_path": "other.py",
            "new_path": "other.py",
            "hunks": (first.hunks[0].model_copy(update={"id": "other-hunk"}),),
        }
    )
    reader.scope = reader.scope.model_copy(update={"files": (first, second)})
    repository.files["other.py"] = replace(
        repository.files["customers.py"], path="other.py"
    )
    await broker.start("head", base="base")
    for number, batch in enumerate(broker.batches(), 1):
        broker.begin_batch(batch, f"batch-{number}:")
        item = request(origin_hunk_id=batch.files[0].hunks[0].id)
        broker.open_question(item.question_id, item.question, item.origin_hunk_id)
        audit = await broker.read(item)
        assert audit.action == "read"
        broker.answer(
            item.question_id,
            "The helper returns the stored value.",
            (audit.snippet.id,),
        )
    report = broker.finish()
    counters = {counter.resource: counter.used for counter in report.counters}
    assert counters["scoped_searches"] == 2
    assert counters["additional_files"] == 1
    assert report.complete
