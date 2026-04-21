from rest_framework import serializers
from .models import app_user, task_management, assignment, statusoption, priorityoption, notification, forum_entry

class UserSerializer(serializers.ModelSerializer):
    user_id = serializers.IntegerField(source='id', read_only=True)
    class Meta:
        model = app_user
        fields = ['id', 'user_id', 'name', 'email', 'role', 'phone', 'status', 'profile_image', 'deleted']

class TaskTemplateSerializer(serializers.ModelSerializer):
    priority = serializers.SerializerMethodField()
    
    def get_priority(self, obj):
        return obj.priority.name if obj.priority else 'None'
    
    class Meta:
        model = task_management
        fields = ['id', 'title', 'description', 'priority', 'dtm_created']

class AssignmentSerializer(serializers.ModelSerializer):
    task_title = serializers.CharField(source='task.title', read_only=True)
    task_desc = serializers.CharField(source='task.description', read_only=True)
    user_name = serializers.CharField(source='assigned_to.name', read_only=True)
    
    # Map to names as expected by frontend with null-safety
    title = serializers.CharField(source='task.title', read_only=True)
    priority = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    
    def get_priority(self, obj):
        try:
            return obj.task.priority.name if obj.task.priority else 'None'
        except Exception:
            return 'None'

    def get_status(self, obj):
        return obj.status.name if obj.status else 'Pending'

    # Critical for Frontend ID mapping
    task_id = serializers.IntegerField(source='task.id', read_only=True)
    emp_id = serializers.IntegerField(source='assigned_to.id', read_only=True)
    user_id = serializers.IntegerField(source='assigned_to.id', read_only=True)

    class Meta:
        model = assignment
        fields = [
            'id', 'task', 'task_id', 'assigned_to', 'emp_id', 'user_id', 
            'title', 'task_title', 'task_desc', 'user_name', 
            'priority', 'status', 'assigned_by',
            'start_date', 'deadline', 'end_date', 'comments', 'dtm_created'
        ]

class NotificationSerializer(serializers.ModelSerializer):
    class Meta:
        model = notification
        fields = ['id', 'user', 'title', 'message', 'status', 'created_at']

class ForumEntrySerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.name', read_only=True)
    
    class Meta:
        model = forum_entry
        fields = ['id', 'user', 'user_name', 'message', 'reply', 'status', 'sender_role', 'is_read', 'dtm_created']
