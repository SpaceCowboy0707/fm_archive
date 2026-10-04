"""Conservative local handling of unsupported real-world weather requests."""
import re
from src.i18n import INPUT_ALIASES


def unsupported_request(question):
    text=question.casefold()
    weather=bool(re.search(INPUT_ALIASES['weather'],text))
    archive=bool(re.search(INPUT_ALIASES['archive'],text))
    if weather and not archive:
        return {
            'reason':"Real-world weather request. This website has FM archive tools but no live weather source.",
            'answer':"This website cannot retrieve live weather.\n\n**Why it is unavailable**\n\n"
                     "- The connected source is an FM archive database, without a forecast tool or live weather service.\n"
                     "- Game dates cannot establish tomorrow's real-world weather.\n\n"
                     "**Missing information**\n\n"
                     "- A current forecast for the requested location, including temperature, precipitation and wind.\n"
                     "- A city name alone is insufficient without a weather source.\n\n"
                     "No football records will be queried and no forecast will be invented."}
    return None
