import os
import time

from django.contrib.staticfiles.management.commands.runserver import Command as StaticRunserverCommand
from django.utils import autoreload

from api import dev_stack


class Command(StaticRunserverCommand):
    def add_arguments(self, parser):
        super().add_arguments(parser)
        parser.add_argument(
            "--no-worker", action="store_false", dest="start_worker",
            help="Do not start the Celery worker (or Redis) automatically.")

    def run(self, **options):
        worker = None
        is_parent = os.environ.get(autoreload.DJANGO_AUTORELOAD_ENV) != "true"
        if options.get("start_worker", True) and is_parent:
            worker = self._start_stack()
        try:
            super().run(**options)
        finally:
            if worker is not None:
                dev_stack.stop_worker(worker)
                self.stdout.write("Celery worker stopped.")

    def _start_stack(self):
        dev_stack.ensure_broker(self.stdout.write)
        if dev_stack.worker_already_running():
            self.stdout.write("A Celery worker is already running; not starting another.")
            return None
        try:
            proc = dev_stack.start_worker()
        except OSError as exc:
            self.stdout.write(self.style.ERROR(f"Could not start Celery worker: {exc}"))
            return None
        self.stdout.write(self.style.SUCCESS(f"Celery worker started (pid {proc.pid})."))
        time.sleep(2)
        exit_code = proc.poll()
        if exit_code is not None:
            message = (f"Celery worker exited immediately with exit code {exit_code}; run: "
                       "celery -A nomadaapolo worker -l info --concurrency=1")
            self.stdout.write(self.style.ERROR(message))
            return None
        return proc
