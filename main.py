import logging

import aiorun
import uvloop

from core import delta


# Create a custom formatter for prettier logs
class PrettyFormatter(logging.Formatter):
    def __init__(self):
        fmt = "%(asctime)s | %(name)s | %(levelname)s | %(message)s"
        datefmt = "%Y-%m-%d %H:%M:%S"
        super().__init__(fmt=fmt, datefmt=datefmt)


# Set up the logger for your application
logger = logging.getLogger("Delta")
logger.setLevel(logging.INFO)
stream_handler = logging.StreamHandler()
stream_handler.setFormatter(PrettyFormatter())
logger.addHandler(stream_handler)
logger.propagate = False

# Set Pyrogram's loggers to a higher level to silence info/debug messages
logging.getLogger("pyrogram").setLevel(logging.WARNING)


async def main():
    await delta.start_clients()
    logger.info("Delta Started!")


if __name__ == "__main__":
    uvloop.install()
    aiorun.run(main())
