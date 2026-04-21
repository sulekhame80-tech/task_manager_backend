from django.db import models
from django.utils import timezone


# master tables
class statusoption(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'master_status'
        ordering = ['name']


class priorityoption(models.Model):
    name = models.CharField(max_length=100, unique=True)

    class Meta:
        db_table = 'master_priority'
        ordering = ['name']





# user
class app_user(models.Model):
    name = models.CharField(max_length=255)
    email = models.EmailField(unique=True, db_index=True)
    phone = models.CharField(max_length=20, unique=True, null=True, blank=True)
    password = models.CharField(max_length=128)

    role = models.CharField(max_length=50, default='employee', db_index=True)
    status = models.CharField(max_length=50, default='active', db_index=True)

    deleted = models.BooleanField(default=False, db_index=True)

    created_by = models.CharField(max_length=100, null=True, blank=True)
    dtm_created = models.DateTimeField(default=timezone.now)

    modified_by = models.CharField(max_length=100, null=True, blank=True)
    dtm_modified = models.DateTimeField(auto_now=True)

    remarks = models.TextField(null=True, blank=True)
    profile_image = models.TextField(null=True, blank=True) # Base64 string
    last_seen = models.DateTimeField(null=True, blank=True, db_index=True)

    class Meta:
        db_table = 'user'
        ordering = ['name']


# task
class task_management(models.Model):
    title = models.CharField(max_length=255)
    description = models.TextField()

    priority = models.ForeignKey(priorityoption, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.ForeignKey(statusoption, on_delete=models.SET_NULL, null=True, blank=True)

    deleted = models.BooleanField(default=False, db_index=True)

    created_by = models.CharField(max_length=100, null=True, blank=True)
    dtm_created = models.DateTimeField(default=timezone.now)

    modified_by = models.CharField(max_length=100, null=True, blank=True)
    dtm_modified = models.DateTimeField(auto_now=True)

    company_name = models.CharField(max_length=255, null=True, blank=True)
    lowered_by = models.CharField(max_length=100, null=True, blank=True)

    class Meta:
        db_table = 'task'
        ordering = ['-dtm_created']


# assignment (fixed)
class assignment(models.Model):
    task = models.ForeignKey(task_management, on_delete=models.CASCADE, db_index=True)
    assigned_to = models.ForeignKey(app_user, on_delete=models.CASCADE, db_index=True)

    start_date = models.DateTimeField(null=True, blank=True)
    deadline = models.DateTimeField(null=True, blank=True, db_index=True)
    end_date = models.DateTimeField(null=True, blank=True)

    status = models.ForeignKey(statusoption, on_delete=models.SET_NULL, null=True, blank=True)

    comments = models.TextField(null=True, blank=True)

    notified_start = models.BooleanField(default=False)
    notified_overdue = models.BooleanField(default=False)

    assigned_by = models.CharField(max_length=100, null=True, blank=True)
    timeline = models.JSONField(default=list, blank=True)

    deleted = models.BooleanField(default=False, db_index=True)

    dtm_created = models.DateTimeField(default=timezone.now)
    dtm_modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'assignment'
        ordering = ['-dtm_created']
        indexes = [
            models.Index(fields=['task', 'assigned_to']),
            models.Index(fields=['assigned_to', 'status']),
            models.Index(fields=['deadline']),
        ]


# notification
class notification(models.Model):
    STATUS_CHOICES = [('unread', 'Unread'), ('read', 'Read')]

    user = models.ForeignKey(app_user, on_delete=models.CASCADE, db_index=True)
    title = models.CharField(max_length=255, default='New Notification', null=True, blank=True)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='unread', db_index=True)

    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'notification'
        ordering = ['-created_at']


# forum
class forum_entry(models.Model):
    STATUS_CHOICES = [('pending', 'Pending'), ('resolved', 'Resolved')]

    user = models.ForeignKey(app_user, on_delete=models.CASCADE, db_index=True)
    message = models.TextField()
    reply = models.TextField(null=True, blank=True)

    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='pending', db_index=True)
    
    sender_role = models.CharField(max_length=20, default='user', db_index=True) # 'user' or 'admin'
    is_read = models.BooleanField(default=False, db_index=True)

    deleted = models.BooleanField(default=False, db_index=True)

    dtm_created = models.DateTimeField(default=timezone.now)
    dtm_modified = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'forum'
        ordering = ['-dtm_created']


# log
class system_log(models.Model):
    task = models.ForeignKey(task_management, on_delete=models.SET_NULL, null=True, blank=True)
    user = models.ForeignKey(app_user, on_delete=models.CASCADE, db_index=True)

    action = models.CharField(max_length=255)
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        db_table = 'log'
        ordering = ['-timestamp']


# otp
class otp_entry(models.Model):
    phone = models.CharField(max_length=20, unique=True, db_index=True)
    otp = models.CharField(max_length=10)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = 'otp'
        ordering = ['-created_at']