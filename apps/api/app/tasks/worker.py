import logging
import signal
import threading

from app.core.database import Database
from app.core.config import Settings
from app.tasks.scheduler import tick


def main():
    logging.basicConfig(level=logging.INFO)
    stopped = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stopped.set())
    signal.signal(signal.SIGINT, lambda *_: stopped.set())
    database = Database(Settings())
    while not stopped.is_set():
        try:
            tick(database.session)
        except Exception:
            logging.exception('待办调度本轮失败，将在下一轮重试')
        stopped.wait(10)


if __name__ == '__main__':
    main()
