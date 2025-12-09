def create_suggestion_diff(current: dict, updated: dict) -> dict:
    """
    Eenvoudige helper om alleen velden op te nemen die veranderen.
    Deze gaan we later gebruiken bij echte AI-output.
    """
    diff = {}
    for key, value in updated.items():
        if key not in current or current[key] != value:
            diff[key] = value
    return diff
