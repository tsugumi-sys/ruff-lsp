import argparse
import logging

logging.basicConfig(filename="pygls.log", filemode="w", level=logging.DEBUG)


def main() -> None:
    from ruff_lsp import __version__, server

    parser = argparse.ArgumentParser(prog="ruff-lsp")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )
    parser.parse_args()

    server.start()


if __name__ == "__main__":
    main()
