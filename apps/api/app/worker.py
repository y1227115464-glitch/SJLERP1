import logging
import sys
import time

from rq import SpawnWorker, Worker
from rq.exceptions import StopRequested

from app.core.config import Settings
from app.jobs.service import queue_for, recover_jobs


def main():
    logging.basicConfig(level=logging.INFO)
    settings = Settings()
    worker_class = SpawnWorker if sys.platform == "darwin" else Worker
    while True:
        try:
            recover_jobs(settings)
            queue = queue_for(settings)
            worker_class([queue], connection=queue.connection).work(burst=True, logging_level="WARNING")
            time.sleep(5)
        except (KeyboardInterrupt, StopRequested):
            return
        except Exception as error:
            logging.error("Worker unavailable (%s); recovering in 5 seconds", type(error).__name__)
            try:
                time.sleep(5)
            except (KeyboardInterrupt, StopRequested):
                return


if __name__ == "__main__":
    main()
