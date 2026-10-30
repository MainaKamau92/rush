def safe_repository_path(path: str) -> bool:
    try:
        path.encode()
    except UnicodeEncodeError:
        return False
    return (
        not any(ord(character) < 32 or ord(character) == 127 for character in path)
        and all(part not in {"", ".", ".."} for part in path.split("/"))
        and all(part.lower() != ".git" for part in path.split("/"))
    )
