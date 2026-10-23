import sys

from telemetry import context_size

DIM = "\033[2m"
AMBER = "\033[33m"
RED = "\033[31m"
RESET = "\033[0m"
RED_FROM = context_size.FIRST_THRESHOLD + context_size.THRESHOLD_STEP


def input_tokens(payload):
    window = payload.get("context_window")
    tokens = window.get("total_input_tokens") if isinstance(window, dict) else None
    return tokens if isinstance(tokens, int) and tokens > 0 else None


def colour_for(tokens):
    if tokens >= RED_FROM:
        return RED
    return AMBER if tokens >= context_size.FIRST_THRESHOLD else DIM


def render(payload):
    tokens = input_tokens(payload)
    if tokens is None:
        return ""
    hint = " - consider a handoff" if tokens >= context_size.FIRST_THRESHOLD else ""
    return f"{colour_for(tokens)}ctx {tokens // 1000}k{hint}{RESET}"


def main(stream):
    try:
        print(render(context_size.parse_object(stream.read())))
    except Exception:  # noqa: BLE001
        print("")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.stdin))
