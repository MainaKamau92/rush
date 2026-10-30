from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response

from app.core.errors import ReviewError
from app.dependencies import GitHubReviews, get_github
from app.schemas.github import ReviewJob

router = APIRouter()


def _configured(reviews: GitHubReviews | None) -> GitHubReviews:
    if reviews is None:
        raise HTTPException(status_code=404, detail="GitHub reviews are not configured")
    return reviews


@router.post("/github/webhook")
async def webhook(
    request: Request,
    response: Response,
    reviews: Annotated[GitHubReviews | None, Depends(get_github)],
) -> dict[str, str]:
    receipt = await _configured(reviews).events.receive(
        request.headers.get("x-github-event"),
        request.headers.get("x-github-delivery"),
        request.headers.get("x-hub-signature-256"),
        await request.body(),
    )
    if receipt.status_code >= 400:
        raise HTTPException(status_code=receipt.status_code, detail=receipt.message)
    response.status_code = receipt.status_code
    body = {"message": receipt.message}
    if receipt.job_id is not None:
        body["job"] = receipt.job_id
    return body


@router.get("/jobs", response_model=list[ReviewJob])
async def jobs(
    reviews: Annotated[GitHubReviews | None, Depends(get_github)],
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> tuple[ReviewJob, ...]:
    return await _configured(reviews).worker.recent(limit)


@router.get("/jobs/{job_id}", response_model=ReviewJob)
async def job(
    job_id: str, reviews: Annotated[GitHubReviews | None, Depends(get_github)]
) -> ReviewJob:
    try:
        return await _configured(reviews).worker.get(job_id)
    except ReviewError as error:
        raise HTTPException(status_code=404, detail="Review job not found") from error
