class StateError(Exception):
    pass


class ModelError(Exception):
    pass


class SourceError(Exception):
    pass


class SourceAccessError(SourceError):
    pass


class SourceRateLimitError(SourceError):
    pass


class ReviewError(Exception):
    pass


class ReviewConflictError(ReviewError):
    pass


class ChangeError(Exception):
    pass


class MissingObjectError(ChangeError):
    pass


class InvestigationError(ChangeError):
    pass


class SkillError(ReviewError):
    pass


class CodeHostError(Exception):
    pass
