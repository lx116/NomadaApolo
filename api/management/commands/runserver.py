import os
import signal
import sys
import time

from django.conf import settings
from django.contrib.staticfiles.management.commands.runserver import Command as StaticRunserverCommand
from django.utils import autoreload

from api import dev_stack, queue_actions


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
            self._recover_queue()
        previous_handlers = {}
        if worker is not None:
            for signum in (signal.SIGHUP, signal.SIGTERM):
                try:
                    previous_handlers[signum] = signal.signal(
                        signum, lambda _signum, _frame: sys.exit(0))
                except (ValueError, OSError):
                    pass
        try:
            super().run(**options)
        finally:
            if worker is not None:
                dev_stack.stop_worker(worker)
                self.stdout.write("Celery worker stopped.")
            for signum, handler in previous_handlers.items():
                try:
                    signal.signal(signum, handler)
                except (ValueError, OSError):
                    pass

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

    def _recover_queue(self):
        try:
            result = queue_actions.recover(settings.QUEUE_MONITOR_STALE_MINUTES)
        except Exception as exc:
            self.stdout.write(self.style.WARNING(
                f"Could not re-queue pending audios ({exc.__class__.__name__})."
            ))
            return
        if result["reset"]:
            self.stdout.write(f"Recovered {result['reset']} stuck audio(s).")
        if result["enqueued"]:
            self.stdout.write(f"Re-queued {result['enqueued']} pending audio(s).")
        if not result["broker_ok"]:
            self.stdout.write(self.style.WARNING(
                "Could not reach the broker: "
                f"{result['failed']} pending audio(s) were not queued. "
                "Use the Queue panel to retry."
            ))
