class StateError(Exception):
    pass


class ModelError(Exception):
    pass


class SourceError(Exception):
    pass


class ReviewError(Exception):
    pass


class ReviewConflictError(ReviewError):
    pass


class ChangeError(Exception):
    pass


class MissingObjectError(ChangeError):
    pass
