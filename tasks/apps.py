from django.apps import AppConfig


class TasksConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'tasks'

    def ready(self):
        import sys
        import os
        # 🚀 Skip background worker during migrations/management commands
        if any(arg in sys.argv for arg in ['makemigrations', 'migrate', 'collectstatic', 'check']):
            return

        # 🚀 Only start engine in the main process (skips Django reloader replica)
        if os.environ.get('RUN_MAIN') != 'true' and 'runserver' in sys.argv:
            return

        # 🚀 Start the background automation engine (Django DB based)
        from .tasks import repair_live_database
        repair_live_database()
        
        from .background_worker import start_automation_engine
        start_automation_engine()
