import argparse
import sys

from .agent import SupportAgent

BANNER = (
    "Aster & Row support agent. Type a question, or /reset to start a new session, "
    "or /quit to exit."
)


def main(argv=None):
    parser = argparse.ArgumentParser(description="Aster & Row support agent")
    parser.add_argument("--session", default="cli")
    parser.add_argument("--debug", action="store_true", help="print the full trace for each turn")
    parser.add_argument("--ask", help="answer a single question and exit")
    arguments = parser.parse_args(argv)

    agent = SupportAgent(debug=arguments.debug)

    if arguments.ask:
        print(agent.ask(arguments.ask, session_id=arguments.session).display())
        return 0

    print(BANNER)
    while True:
        try:
            message = input("\nyou > ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not message:
            continue
        if message in ("/quit", "/exit"):
            return 0
        if message == "/reset":
            agent.store.reset(arguments.session)
            print("session cleared")
            continue
        response = agent.ask(message, session_id=arguments.session)
        print("\nagent >", response.display())


if __name__ == "__main__":
    sys.exit(main())
