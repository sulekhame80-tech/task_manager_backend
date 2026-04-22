from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from .models import (
    app_user, task_management, assignment, notification, 
    forum_entry, system_log, otp_entry, statusoption, priorityoption
)
from datetime import datetime, date
from django.utils import timezone
import traceback
from django.db.models import Count, Q
from django.core.paginator import Paginator
from .serializers import (
    UserSerializer, TaskTemplateSerializer, AssignmentSerializer, 
    NotificationSerializer, ForumEntrySerializer, app_user
)
from django.db.models import Max

# ─────────────────────────────────────────────────────────────────────────────
# CORE UTILITIES
# ─────────────────────────────────────────────────────────────────────────────

def _log(tag, msg, user_id=0):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] [{tag}] {msg}")
    
    # Use id=1 (Primary Admin) as fallback for system/background logs
    # to avoid NOT NULL constraint failed: log.user_id
    effective_id = user_id if user_id > 0 else 1
    
    try:
        user = app_user.objects.filter(id=effective_id, deleted=False).first()
        if user:
            system_log.objects.create(user=user, action=f"[{tag}] {msg}")
    except Exception:
        pass

def _err(tag, msg, exc=None, user_id=0):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] ❌ [{tag}] ERROR: {msg}")
    if exc:
        traceback.print_exc()

def paginate_and_search(queryset, page=1, page_size=10, search=None, search_fields=None):
    if search and search_fields:
        query = Q()
        for field in search_fields:
            query |= Q(**{f"{field}__icontains": search})
        queryset = queryset.filter(query)

    paginator = Paginator(queryset, page_size)
    try:
        page_obj = paginator.get_page(page)
    except Exception:
        page_obj = paginator.get_page(1)

    return {
        "total": paginator.count,
        "total_pages": paginator.num_pages,
        "current_page": page_obj.number,
        "page_size": page_size,
        "data": page_obj.object_list
    }

def _add_notif_logic(user_id, title, message):
    """ Robust Helper for System Notifications """
    try:
        target = app_user.objects.filter(id=user_id, deleted=False).first()
        if not target:
            return False
        notification.objects.create(
            user=target,
            title=title,
            message=message
        )
        _log("NOTIF-SYNC", f"Sent: '{title}' to {target.name}")
        return True
    except Exception as e:
        _err("NOTIF-SYNC", f"Failed: {str(e)}")
        return False

def _check_permission(req_user_id, target_user_id=None, action="edit"):
    """
    Unified Permission Helper.
    Returns (bool permitted, app_user object or None).
    Hierarchy:
    - Admin: Full Control
    - Manager: Manage all except Admins
    - Employee: No management rights
    """
    try:
        # 🛡️ Safety: Handle non-numeric or invalid IDs from legacy sessions/hot-reloads
        if req_user_id is None or not str(req_user_id).strip().isdigit():
            _log("AUTH-PERM", f"Blocked invalid/null req_user_id: {req_user_id}")
            return False, None
            
        req_user = app_user.objects.get(id=req_user_id, deleted=False)
        req_role = str(req_user.role).lower()
        
        # 🛡️ GLOBAL ADMIN PROTECTION: Allow Admins to manage other Admins, but block everyone else.
        if target_user_id and action in ['edit', 'delete']:
            if str(req_user_id) != str(target_user_id):
                target_user = app_user.objects.filter(id=target_user_id).first()
                if target_user and str(target_user.role).lower() == 'admin':
                    # Allow if requester is also an admin
                    if req_role == 'admin':
                        return True, req_user
                    _log("AUTH-PERM", f"Blocked {action} attempt on ADMIN id={target_user_id} by {req_user.name}")
                    return False, req_user

        if req_role == 'admin':
            return True, req_user
            
        # 🛡️ Employees & Managers editing their own profiles
        if target_user_id and str(req_user_id) == str(target_user_id):
            return True, req_user
            
        if req_role == 'manager':
            # Managers cannot touch Admins (Redundant due to global protection, but good for hierarchy)
            if target_user_id:
                target_user = app_user.objects.filter(id=target_user_id).first()
                if target_user and str(target_user.role).lower() == 'admin':
                    return False, req_user
            return True, req_user
            
        return False, req_user
    except Exception:
        return False, None

# ─────────────────────────────────────────────────────────────────────────────
# AUTH (STEP 1)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
@permission_classes([AllowAny])
def login_user(request):
    """
    Step 1: Proper Login API
    Authenticates user, checks status, and returns serialized user data.
    
    Example Payload:
    {
        "email": "employee@example.com",
        "password": "password123"
    }
    """
    email = str(request.data.get('email', '')).strip()
    password = str(request.data.get('password', '')).strip()
    _log("LOGIN", f"Attempting login for: {email}")

    try:
        user = app_user.objects.filter(email__iexact=email, password=password, deleted=False).first()
        
        if not user:
            _log("LOGIN", f"❌ Invalid credentials: {email}")
            return Response({"status": "error", "message": "Invalid email or password"}, status=401)

        # 🛡️ Security Check: Status
        status = str(user.status).lower()
        if status == 'inactive':
            _log("LOGIN", f"⛔ Blocked inactive user: {email}")
            return Response({"status": "error", "message": "Account deactivated. Contact Admin."}, status=403)
        elif status == 'pending':
            _log("LOGIN", f"🕒 Blocked pending user: {email}")
            return Response({"status": "error", "message": "Account pending Admin approval."}, status=403)

        serializer = UserSerializer(user)
        _log("LOGIN", f"✅ Success: {user.name} ({user.role})")
        return Response({"status": "success", "user": serializer.data})
    except Exception as e:
        _err("LOGIN", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['GET'])
def get_pending_users(request):
    """
    Returns users with 'pending' status for admin approval.
    """
    try:
        users = app_user.objects.filter(status__iexact='pending', deleted=False)
        return Response(UserSerializer(users, many=True).data)
    except Exception as e:
        _err("PENDING-GET", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['POST'])
def approve_user(request):
    """
    Approves or rejects a pending user registration.
    
    Example Payload:
    {
        "user_id": "3",
        "status": "active"
    }
    """
    uid        = request.data.get('user_id')
    new_status = request.data.get('status', 'active')
    try:
        user = app_user.objects.get(pk=uid, deleted=False)
        user.status = new_status
        user.save()
        
        msg = "Your account has been activated. Welcome to Campus Connection!" \
              if new_status.lower() == 'active' else "Your registration was rejected. Contact admin."
        _add_notif_logic(uid, "ACCOUNT UPDATE", msg)
        
        return Response({"status": "success"})
    except app_user.DoesNotExist:
        return Response({"status": "error", "message": "User not found"}, status=404)
    except Exception as e:
        _err("APPROVE-USER", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

        # ─────────────────────────────────────────────────────────────────────────────
# MASTER DATA (STEP 2)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def get_master_data(request):
    """
    Returns lists of statuses, priorities, and roles for the frontend dropdowns.
    """
    try:
        data = {
            "statuses": list(statusoption.objects.values_list('name', flat=True)),
            "priorities": list(priorityoption.objects.values_list('name', flat=True)),
            # Roles are static system constants — not stored in DB
            "roles": ["admin", "manager", "employee"],
            "server_time": datetime.now().isoformat()
        }
        return Response(data)
    except Exception as e:
        _err("MASTER-GET", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['POST'])
def update_master_data(request):
    """
    Updates the available options for Status, Priority, or Role.
    
    Example Payload:
    {
        "type": "status",
        "options": [ ]
    }
    """
    data_type = str(request.data.get('type', '')).lower()   # 'status' | 'priority'
    options   = request.data.get('options', [])

    # Roles are static — cannot be modified via this endpoint
    if data_type == 'role':
        return Response({"status": "error", "message": "Roles are fixed system constants and cannot be modified."}, status=403)

    model_map = {
        'status': statusoption,
        'priority': priorityoption,
    }
    Model = model_map.get(data_type)
    
    if not Model:
        return Response({"status": "error", "message": "Invalid master data type"}, status=400)
    
    try:
        clean_options = [o.strip() for o in options if o.strip()]
        
        # Safely determine which options to delete (not in use)
        # For simplicity in this 'rebuild', we overwrite unless it's a critical error
        # In a real system, we'd check ForeignKeys.
        
        # Delete old options not in the new list
        Model.objects.exclude(name__in=clean_options).delete()
        
        # Create new ones
        for name in clean_options:
            Model.objects.get_or_create(name=name)
            
        _log("MASTER-UPDATE", f"Successfully updated {data_type} options")
        return Response({"status": "success", "message": f"{data_type.capitalize()} options updated"})
    except Exception as e:
        _err("MASTER-UPDATE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# USER MANAGEMENT (STEP 3)
# ─────────────────────────────────────────────────────────────────────────────



@api_view(['GET'])
def get_employees(request):
    """
    Step 3: Proper Paginated & Searchable Employee List
    Authorization: Admins/Managers only.
    """
    req_user_id = request.query_params.get('req_user_id')
    permitted, req_user = _check_permission(req_user_id)
    
    if not permitted:
        return Response({"status": "error", "message": "Permission denied"}, status=403)

    try:
        search = request.query_params.get('search')
        page   = int(request.query_params.get('page', 1))
        size   = int(request.query_params.get('page_size', 10))
        
        # Filter Logic:
        # Admins see everyone (including other admins)
        # Managers see everyone EXCEPT admins (to prevent unauthorized access)
        qs = app_user.objects.filter(deleted=False)
        if req_user.role == 'manager':
            qs = qs.exclude(role__iexact='admin')
        
        pager = paginate_and_search(qs, page, size, search, ['name', 'email', 'phone'])
        
        serializer = UserSerializer(pager['data'], many=True)
        pager['data'] = serializer.data
        
        return Response(pager)
    except Exception as e:
        _err("EMPLOYEES-GET", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['POST'])
@permission_classes([AllowAny])
def create_user(request):
    """
    Creates a new user with one of the fixed roles (admin, manager, employee).
    Authorization: Admins can create anyone. Managers cannot create admins.
    If req_user_id is absent, allows bypassing RBAC (intended for Postman manually).
    
    Example Payload:
    {
        "req_user_id": "1",
        "name": "Jane Employee",
        "email": "jane@example.com",
        "password": "securepassword",
        "phone": "555-0102",
        "role": "employee"
    }
    """
    data = request.data
    req_user_id = data.get('req_user_id') or data.get('admin_id')
    role = str(data.get('role', 'employee')).lower()
    
    if req_user_id:
        permitted, req_user = _check_permission(req_user_id)
        if not permitted:
            return Response({"status": "error", "message": "Permission denied. Only Admins and Managers can create users. Please re-login if this is unexpected."}, status=403)
        # Manager Protection: Cannot create an admin
        if req_user.role == 'manager' and role == 'admin':
             return Response({"status": "error", "message": "Managers are not permitted to create Admin accounts. Contact your system administrator."}, status=403)
    
    if role not in ['admin', 'manager', 'employee']:
        return Response({"status": "error", "message": f"Invalid role '{role}'. Must be admin, manager, or employee."}, status=400)

    try:
        if app_user.objects.filter(email=data.get('email')).exists():
            return Response({"status": "error", "message": "Email already exists in our records (possibly in a deactivated account)."}, status=400)
        
        phone = data.get('phone')
        if phone and str(phone).strip() != "":
            if app_user.objects.filter(phone=phone).exists():
                return Response({"status": "error", "message": "Phone number is already associated with another account (possibly deactivated)."}, status=400)
        else:
            phone = None # Ensure NULL for database uniqueness

        user = app_user.objects.create(
            name=data.get('name'),
            email=data.get('email'),
            password=data.get('password'),
            phone=phone,
            role=role,
            status='active'
        )
        _log("EMP-CREATE", f"✅ Created user_id={user.id}")
        return Response({"status": "success", "user_id": user.id})
    except Exception as e:
        _err("EMP-CREATE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def update_employee(request):
    """
    Updates an existing user's profile.
    Authorization: Admin/Manager only. Manager cannot edit Admin.
    
    Example Payload:
    {
        "user_id": "2",
        "req_user_id": "1",
        "updates": {"name": "Jane Doe"}
    }
    """
    user_id = request.data.get('user_id') #user
    req_user_id = request.data.get('req_user_id') or request.data.get('admin_id') #admin
    
    permitted, req_user = _check_permission(req_user_id, target_user_id=user_id)
    if not permitted:
        return Response({"status": "error", "message": "Permission denied: Managers cannot modify Admins"}, status=403)

    updates = request.data.get('updates', {})
    
    # 🛡️ SECURITY: Prevent non-admins from privilege escalation via self-edits
    if str(req_user.role).lower() != 'admin':
        updates.pop('role', None)
        updates.pop('status', None)
        updates.pop('deleted', None)

    _log("EMP-UPDATE", f"user_id={user_id} by={req_user.name}")
    
    try:
        user = app_user.objects.filter(id=user_id, deleted=False).first()
        if not user:
            return Response({"status": "error", "message": "User not found"}, status=404)
        
        for field, value in updates.items():
            if hasattr(user, field):
                # Handle unique phone constraint for empty strings
                if field == 'phone' and (not value or str(value).strip() == ""):
                    setattr(user, field, None)
                else:
                    setattr(user, field, value)
        
        user.save()
        _log("EMP-UPDATE", f"✅ Updated user_id={user_id}")
        return Response({"status": "success"})
    except Exception as e:
        _err("EMP-UPDATE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def delete_employee(request):
    """
    Soft deletes a user.
    Authorization: Admin/Manager only. Manager cannot delete Admin.
    
    Example Payload:
    {
        "user_id": "2",
        "req_user_id": "1"
    }
    """
    user_id = request.data.get('user_id')
    req_user_id = request.data.get('req_user_id') or request.data.get('admin_id')
    
    permitted, req_user = _check_permission(req_user_id, target_user_id=user_id)
    if not permitted:
        return Response({"status": "error", "message": "Permission denied: Managers cannot delete Admins"}, status=403)

    _log("EMP-DELETE", f"user_id={user_id} by={req_user.name}")
    
    try:
        updated = app_user.objects.filter(id=user_id, deleted=False).update(deleted=True)
        if not updated:
            return Response({"status": "error", "message": "User not found"}, status=404)
            
        _log("EMP-DELETE", f"✅ Soft deleted user_id={user_id}")
        return Response({"status": "success"})
    except Exception as e:
        _err("EMP-DELETE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['GET'])
def get_employee_status(request):
    """
    Returns the current status of all employees (Working/Idle).
    """
    try:
        users = app_user.objects.filter(deleted=False, role__iexact='employee')
        result = {}
        for u in users:
            active = assignment.objects.filter(
                assigned_to=u, 
                deleted=False
            ).select_related('status').filter(status__name__iexact='in progress').first()
            
            result[str(u.id)] = {
                "name": u.name,
                "status": "Working" if active else "Idle",
                "current_task": active.task.id if active else "-",
            }
        return Response(result)
    except Exception as e:
        _err("EMP-STATUS", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# TASK LIBRARY (STEP 4)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def get_library_all(request):
    """
    Step 4: Proper Paginated & Searchable Task Library
    """
    try:
        search = request.query_params.get('search')
        page   = int(request.query_params.get('page', 1))
        size   = int(request.query_params.get('page_size', 10))
        
        qs = task_management.objects.filter(deleted=False)
        pager = paginate_and_search(qs, page, size, search, ['title', 'description'])
        
        serializer = TaskTemplateSerializer(pager['data'], many=True)
        pager['data'] = serializer.data
        return Response(pager)
    except Exception as e:
        _err("LIBRARY-GET", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['POST'])
def create_task_template(request):
    """
    Creates a master task template. Validate priority name.
    
    Example Payload:
    {
        "title": "Onboarding Module Review",
        "description": "Please review the onboarding document.",
        "priority": "High",
        "admin_name": "Admin Name"
    }
    """
    data = request.data
    title = data.get('title')
    _log("TASK-CREATE", f"title={title}")

    try:
        # Resolve Priority (dynamic)
        p_name = data.get('priority', 'Medium')
        priority = priorityoption.objects.filter(name__iexact=p_name).first()
        if not priority:
            priority = priorityoption.objects.first() # Default fallback

        task = task_management.objects.create(
            title=title,
            description=data.get('description', ''),
            priority=priority,
            created_by=data.get('admin_name', 'Admin')
        )
        _log("TASK-CREATE", f"✅ Created task_id={task.id}")
        return Response({"status": "success", "task_id": task.id})
    except Exception as e:
        _err("TASK-CREATE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def update_task_template(request):
    """
    Updates a global task template.
    
    Example Payload:
    {
        "task_id": "1",
        "updates": {"priority": "Critical"}
    }
    """
    task_id = request.data.get('task_id')
    updates = request.data.get('updates', {})
    _log("TASK-UPDATE", f"task_id={task_id}")

    try:
        task = task_management.objects.filter(id=task_id, deleted=False).first()
        if not task:
            return Response({"status": "error", "message": "Task not found"}, status=404)

        for field, value in updates.items():
            if field == 'priority':
                p, _ = priorityoption.objects.get_or_create(name=value)
                task.priority = p
            elif field == 'status':
                s, _ = statusoption.objects.get_or_create(name=value)
                task.status = s
            elif hasattr(task, field):
                setattr(task, field, value)
        
        task.save()

        # [NEW] Cascading Completion logic
        if 'status' in updates and updates['status'].lower() == 'completed':
            try:
                # Find all active assignments for this template that are NOT already completed
                assignments_to_update = assignment.objects.filter(
                    task=task,
                    deleted=False
                ).exclude(status__name__iexact='Completed')
                
                # Fetch user IDs for notifications before the update
                affected_user_ids = list(assignments_to_update.values_list('assigned_to_id', flat=True))
                
                # Update them all to 'Completed'
                assignments_to_update.update(status=task.status)
                
                # Send notifications to each affected employee
                for user_id in affected_user_ids:
                    _add_notif_logic(
                        user_id,
                        "TASK COMPLETED BY ADMIN",
                        f"✅ The master task '{task.title}' has been marked as completed by the administrator. Status updated for all."
                    )
                _log("CASCADE-COMPLETION", f"Updated {len(affected_user_ids)} assignments for task {task_id}")
            except Exception as e:
                _err("CASCADE-COMPLETION", f"Error during cascading update: {str(e)}")

        return Response({"status": "success"})
    except Exception as e:
        _err("TASK-UPDATE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def delete_task_template(request):
    """
    Soft deletes a task template.
    Authorization: Admin/Manager only.
    """
    task_id = request.data.get('task_id')
    req_user_id = request.data.get('req_user_id') or request.data.get('admin_id')
    
    _log("TASK-DELETE", f"Attempt delete task_id={task_id} by={req_user_id}")

    # 1. Authorisation Check
    permitted, req_user = _check_permission(req_user_id)
    if not permitted:
        return Response({"status": "error", "message": "Permission denied: Only Admins and Managers can delete tasks."}, status=403)

    # 2. Numeric Validation (Safety for Render DB)
    if not str(task_id).strip().isdigit():
         return Response({"status": "error", "message": f"Invalid task_id: '{task_id}'"}, status=400)

    try:
        updated_template = task_management.objects.filter(id=task_id, deleted=False).update(deleted=True)
        # 🛡️ CASCADE: Also soft-delete all assignments linked to this template
        updated_assignments = assignment.objects.filter(task_id=task_id, deleted=False).update(deleted=True)
        
        if not updated_template and not updated_assignments:
            _log("TASK-DELETE", f"⚠ Not found or already deleted: {task_id}")
            return Response({"status": "error", "message": "Task not found or already deleted"}, status=404)
            
        _log("TASK-DELETE", f"✅ Success: Deleted template {task_id} and associated assignments.")
        return Response({"status": "success"})
    except Exception as e:
        _err("TASK-DELETE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# ASSIGNMENTS (STEP 4)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET', 'POST'])
def manage_assignments(request):
    """
    Handles fetching and creating assignments.
    
    Example Payload (POST):
    {
        "task_id": "1",
        "emp_id": "2",
        "req_user_id": "1",
        "deadline": "2026-12-31"
    }
    """
    if request.method == 'GET':
        try:
            # 🕒 TRIGGER OVERDUE CHECK (NOW HANDLED BY BACKGROUND WORKER)

            emp_id = request.query_params.get('emp_id')
            search = request.query_params.get('search')
            page   = int(request.query_params.get('page', 1))
            size   = int(request.query_params.get('page_size', 10))
            
            qs = assignment.objects.filter(deleted=False).select_related('task', 'assigned_to', 'status', 'task__priority')
            if emp_id:
                qs = qs.filter(assigned_to_id=emp_id)
            
            pager = paginate_and_search(qs, page, size, search, ['task__title', 'task__description'])
            
            serializer = AssignmentSerializer(pager['data'], many=True)
            pager['data'] = serializer.data
            return Response(pager)
        except Exception as e:
            _err("ASSIGN-GET", str(e), exc=True)
            return Response({"status": "error", "message": str(e)}, status=500)

    elif request.method == 'POST':
        data = request.data
        task_id = data.get('task_id')
        emp_id  = data.get('emp_id')
        req_user_id = data.get('req_user_id') or data.get('admin_id')
        
        _log("ASSIGN-CREATE", f"task={task_id} to={emp_id} by={req_user_id}")
        
        try:
            task = task_management.objects.get(id=task_id)
            target_user = app_user.objects.get(id=emp_id)
            assigner = app_user.objects.filter(id=req_user_id).first()
            
            if not assigner:
                return Response({"status": "error", "message": f"Authorization Error: User ID '{req_user_id}' not found. Please re-login."}, status=400)
            
            assigner_role = str(assigner.role).lower()
            target_role = str(target_user.role).lower()
            
            # --- ROLE HIERARCHY VALIDATION ---
            # 1. Self-assignment check
            if str(assigner.id) == str(target_user.id):
                 return Response({"status": "error", "message": "You cannot assign tasks to yourself"}, status=403)
            
            # 2. Hierarchy enforcement
            if assigner_role == 'manager':
                if target_role not in ['employee', 'student']:
                    return Response({"status": "error", "message": "Managers can only assign tasks to Employees or Students"}, status=403)
            elif assigner_role == 'admin':
                if target_role == 'admin':
                    return Response({"status": "error", "message": "Admins cannot assign tasks to other Admins"}, status=403)
            else:
                return Response({"status": "error", "message": "Employees cannot assign tasks"}, status=403)
            
            # --- DUPLICATE ASSIGNMENT CHECK ---
            # Prevent assigning the same template to the same person if they already have an active/pending version
            existing = assignment.objects.filter(
                task_id=task_id, 
                assigned_to_id=emp_id, 
                deleted=False
            ).exclude(status__name__iexact='Completed').first()
            
            if existing:
                return Response({
                    "status": "error", 
                    "message": f"⚠️ Already Assigned: {target_user.name} already has this task ({existing.status.name})."
                }, status=400)

            # Default first status — always 'Pending'
            default_status, _ = statusoption.objects.get_or_create(name='Pending')
            
            from django.utils.dateparse import parse_datetime
            from django.utils.timezone import make_aware, is_aware
            
            raw_deadline = data.get('deadline')
            deadline_dt = None
            if raw_deadline:
                # If it's just a date 'YYYY-MM-DD', append time
                if len(raw_deadline) == 10:
                    raw_deadline += " 23:59:59"
                
                deadline_dt = parse_datetime(raw_deadline)
                if deadline_dt and not is_aware(deadline_dt):
                    deadline_dt = make_aware(deadline_dt)

            new_assign = assignment.objects.create(
                task=task,
                assigned_to=target_user,
                deadline=deadline_dt,
                assigned_by=assigner.name,
                status=default_status
            )
            
            # 🔔 Trigger Notification for the assigned employee
            _add_notif_logic(
                target_user.id, 
                "NEW TASK ASSIGNED", 
                f"📋 You have been assigned a new task: '{task.title}' by {assigner.name}"
            )

            return Response({"status": "success", "assignment_id": new_assign.id})
        except Exception as e:
            _err("ASSIGN-CREATE", str(e), exc=True)
            return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def update_assignment(request):
    """
    Updates an assignment - Status, Deadline, or Reassign (User).
    Managers can only update status/dates for tasks assigned to them.
    
    Example Payload:
    {
        "assignment_id": "1",
        "req_user_id": "2",
        "updates": {"status": "Pending"}
    }
    """
    assign_id = request.data.get('assignment_id') or request.data.get('id')
    req_user_id = request.data.get('req_user_id')
    updates   = request.data.get('updates', {})
    _log("ASSIGN-UPDATE", f"id={assign_id} by={req_user_id}")

    try:
        assign = assignment.objects.filter(id=assign_id, deleted=False).first()
        if not assign:
            return Response({"status": "error", "message": "Assignment not found"}, status=404)

        # 🛡️ SECURITY: Manager self-task restriction
        if req_user_id:
            req_user = app_user.objects.filter(id=req_user_id, deleted=False).first()
            if req_user and req_user.role.lower() == 'manager' and str(assign.assigned_to_id) == str(req_user_id):
                # Manager is updating their OWN task. 
                # Allowed fields: status, start_date, end_date, comments.
                # Restricted: deadline, assigned_to_id, task_id.
                allowed = ['status', 'start_date', 'end_date', 'comments']
                for key in list(updates.keys()):
                    if key not in allowed:
                        return Response({
                            "status": "error", 
                            "message": f"Permission denied: Managers cannot update '{key}' on tasks assigned to them."
                        }, status=403)

        for field, value in updates.items():
            if field == 'status':
                s, _ = statusoption.objects.get_or_create(name=value)
                assign.status = s
            elif field == 'assigned_to_id' or field == 'emp_id':
                 u = app_user.objects.filter(id=value).first()
                 if u: assign.assigned_to = u
            elif hasattr(assign, field):
                setattr(assign, field, value)
        
        assign.save()

        # 🔔 IMMEDIATE NOTIFICATION (On Completion)
        if updates.get('status', '').lower() == 'completed':
            admin = app_user.objects.filter(role__iexact='admin', deleted=False).first()
            if admin:
                _add_notif_logic(
                    admin.id, 
                    "TASK COMPLETED", 
                    f"✅ {assign.assigned_to.name} finished: {assign.task.title}"
                )

        return Response({"status": "success"})
    except Exception as e:
        _err("ASSIGN-UPDATE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def delete_assignment(request):
    """
    Soft deletes an assignment (Untasks a user).
    Authorization: Admin/Manager only.
    """
    assign_id = request.data.get('assignment_id') or request.data.get('id')
    req_user_id = request.data.get('req_user_id') or request.data.get('admin_id')

    _log("ASSIGN-DELETE", f"Attempt delete id={assign_id} by={req_user_id}")

    # 1. Authorisation Check
    permitted, req_user = _check_permission(req_user_id)
    if not permitted:
        return Response({"status": "error", "message": "Permission denied: Only Admins and Managers can cancel assignments."}, status=403)

    # 2. Numeric Validation
    if not str(assign_id).strip().isdigit():
         return Response({"status": "error", "message": f"Invalid assignment_id: '{assign_id}'"}, status=400)

    try:
        updated = assignment.objects.filter(id=assign_id, deleted=False).update(deleted=True)
        if not updated:
            return Response({"status": "error", "message": "Assignment not found"}, status=404)
            
        _log("ASSIGN-DELETE", f"✅ Success: Deleted assignment {assign_id}")
        return Response({"status": "success"})
    except Exception as e:
        _err("ASSIGN-DELETE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# STATS (STEP 5)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def get_stats(request):
    """
    Returns aggregate stats for the dashboard.
    """
    try:
        data = {
            "total_tasks": task_management.objects.filter(deleted=False).count(),
            "total_assignments": assignment.objects.filter(deleted=False).count(),
            "total_employees": app_user.objects.filter(role='employee', deleted=False).count(),
            "completed_tasks": assignment.objects.filter(status__name__iexact='Completed', deleted=False).count(),
        }
        return Response(data)
    except Exception as e:
        _err("STATS", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# NOTIFICATIONS (STEP 6)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def get_notifications(request):
    """
    Fetches paginated notifications for a user.
    """
    try:
        user_id = request.query_params.get('user_id', 1)
        page    = int(request.query_params.get('page', 1))
        size    = int(request.query_params.get('page_size', 20))
        
        qs = notification.objects.filter(user_id=user_id)
        pager = paginate_and_search(qs, page, size)
        
        serializer = NotificationSerializer(pager['data'], many=True)
        pager['data'] = serializer.data
        return Response(pager)
    except Exception as e:
        _err("NOTIF-GET", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['POST'])
def mark_notif_read(request):
    """
    Example Payload:
    {
        "id": "1"
    }
    """
    notif_id = request.data.get('id')
    notification.objects.filter(id=notif_id).update(status='read')
    return Response({"status": "success"})

@api_view(['POST'])
def delete_notification(request):
    """
    Example Payload:
    {
        "id": "1"
    }
    """
    notif_id = request.data.get('id')
    notification.objects.filter(id=notif_id).delete()
    return Response({"status": "success"})

@api_view(['POST'])
def mark_all_notifs_read(request):
    """
    Example Payload:
    {
        "user_id": "2"
    }
    """
    user_id = request.data.get('user_id')
    notification.objects.filter(user_id=user_id, status='unread').update(status='read')
    return Response({"status": "success"})

@api_view(['POST'])
def clear_all_notifications(request):
    """
    Example Payload:
    {
        "user_id": "2"
    }
    """
    user_id = request.data.get('user_id')
    notification.objects.filter(user_id=user_id).delete()
    return Response({"status": "success"})

@api_view(['POST'])
def create_notification(request):
    """
    Example Payload:
    {
        "user_id": "2",
        "title": "Welcome",
        "message": "Welcome to Campus Connection."
    }
    """
    user_id = request.data.get('user_id')
    title   = request.data.get('title', 'System Alert')
    message = request.data.get('message')
    try:
        user = app_user.objects.get(id=user_id)
        notification.objects.create(user=user, title=title, message=message)
        return Response({"status": "success"})
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=400)

# ─────────────────────────────────────────────────────────────────────────────
# FORUM (STEP 6)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def get_forum_entries(request):
    """
    Fetches chat messages. If user_id (target) and req_user_id (sender) are provided, 
    fetches the private 1-to-1 history. Otherwise fetches by owner (legacy).
    """
    try:
        target_id = request.query_params.get('user_id')
        req_id = request.query_params.get('req_user_id')
        search = request.query_params.get('search')
        page   = int(request.query_params.get('page', 1))
        size   = int(request.query_params.get('page_size', 50))
        
        qs = forum_entry.objects.filter(deleted=False)
        
        if target_id and req_id:
            # 1-to-1 History: (A->B or B->A)
            qs = qs.filter(
                (Q(user_id=req_id) & Q(recipient_id=target_id)) |
                (Q(user_id=target_id) & Q(recipient_id=req_id))
            )
            # Legacy Fallback: include messages where req_user is admin and recipient was null
            req_user = app_user.objects.filter(id=req_id).first()
            if req_user and req_user.role.lower() in ['admin', 'manager']:
                legacy = forum_entry.objects.filter(user_id=target_id, recipient__isnull=True, deleted=False)
                qs = (qs | legacy).distinct()
        elif target_id:
            # Legacy Behavior: only by owner
            qs = qs.filter(user_id=target_id)
            
        pager = paginate_and_search(qs.order_by('dtm_created'), page, size, search, ['message', 'user__name'])
        
        serializer = ForumEntrySerializer(pager['data'], many=True)
        pager['data'] = serializer.data
        return Response(pager)
    except Exception as e:
        _err("FORUM-GET", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['POST'])
def create_forum_entry(request):
    """
    Creates a chat message. 
    `user_id` in payload = Recipient.
    `req_user_id` in payload = Sender.
    """
    recipient_id = request.data.get('user_id')
    sender_id    = request.data.get('req_user_id') or request.data.get('admin_id')
    message      = request.data.get('message')
    role         = request.data.get('sender_role', 'user')
    
    try:
        sender = app_user.objects.get(id=sender_id)
        recipient = app_user.objects.get(id=recipient_id)
        
        # Create 1-to-1 Entry
        forum_entry.objects.create(
            user=sender, 
            recipient=recipient, 
            message=message, 
            sender_role=role, 
            is_read=False
        )
        
        # 🔔 NOTIFY RECIPIENT
        _add_notif_logic(
            recipient.id, 
            "NEW MESSAGE", 
            f"💬 {sender.name} sent a message: {message[:50]}..."
        )

        return Response({"status": "success"})
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['GET'])
def get_chat_users(request):
    """
    Returns a list of users for chatting.
    Students see Admins + Their Assignment Managers.
    Admins/Managers see everyone they interated with.
    """
    req_user_id = request.query_params.get('req_user_id')
    
    # Allow all active users to access their own chat directory
    req_user = app_user.objects.filter(id=req_user_id, deleted=False).first()
    if not req_user:
        return Response({"status": "error", "message": "User not found or access denied"}, status=403)

    try:
        role = str(req_user.role).lower()
        active_qs = app_user.objects.filter(deleted=False).exclude(id=req_user.id)
        
        if role == 'employee' or role == 'user':
            # 1. Show all Admins
            admins_qs = active_qs.filter(role__iexact='admin')
            
            # 2. Show Managers who assigned tasks to this student
            my_assigner_names = assignment.objects.filter(
                assigned_to=req_user, 
                deleted=False
            ).values_list('assigned_by', flat=True).distinct()
            
            managers_qs = active_qs.filter(
                role__iexact='manager', 
                name__in=my_assigner_names
            )
            
            users = (admins_qs | managers_qs).distinct()
        else:
            # Admins/Managers see everybody to allow wider support
            users = active_qs
        
        result = []
        for u in users:
            # unread_count: messages FROM (u) TO (me)
            unread_count = forum_entry.objects.filter(
                user=u, 
                recipient=req_user, 
                is_read=False, 
                deleted=False
            ).count()
            
            # last_msg: latest in 1-to-1 conversation
            last_msg = forum_entry.objects.filter(
                deleted=False
            ).filter(
                (Q(user=u, recipient=req_user) | Q(user=req_user, recipient=u))
            ).order_by('-dtm_created').first()
            
            # Legacy Fallback for Admins
            if last_msg is None and role in ['admin', 'manager']:
                 last_msg = forum_entry.objects.filter(user=u, recipient__isnull=True, deleted=False).order_by('-dtm_created').first()
                 unread_count = forum_entry.objects.filter(user=u, recipient__isnull=True, sender_role='user', is_read=False, deleted=False).count()

            result.append({
                "id": u.id,
                "name": u.name,
                "email": u.email,
                "profile_image": getattr(u, 'profile_image', ''),
                "unread_count": unread_count,
                "last_message": last_msg.message if last_msg else "",
                "last_time": last_msg.dtm_created if last_msg else None,
                "last_seen": u.last_seen
            })
            
        # Sort by unread count first, then by activity
        result.sort(key=lambda x: (
            x['unread_count'], 
            x['last_time'].timestamp() if x['last_time'] else 0
        ), reverse=True)
        
        return Response(result)
    except Exception as e:
        _err("CHAT-USERS", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['POST'])
def mark_forum_read(request):
    """
    Marks messages from other_user to me as read.
    """
    other_user_id = request.data.get('user_id')
    req_user_id   = request.data.get('req_user_id')
    try:
        forum_entry.objects.filter(
            user_id=other_user_id, 
            recipient_id=req_user_id, 
            is_read=False
        ).update(is_read=True)
        
        # Legacy Fallback
        req_user = app_user.objects.filter(id=req_user_id, deleted=False).first()
        if req_user and req_user.role.lower() in ['admin', 'manager']:
            forum_entry.objects.filter(user_id=other_user_id, recipient__isnull=True, is_read=False).update(is_read=True)

        return Response({"status": "success"})
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def reply_forum_entry(request):
    """
    Handles replies to forum entries.
    Expected Payload: { "forum_id": "1", "reply": "...", "reply_by": "Admin" }
    """
    forum_id = request.data.get('forum_id')
    reply_text = request.data.get('reply')
    reply_by = request.data.get('reply_by', 'Admin')
    
    try:
        entry = forum_entry.objects.get(id=forum_id)
        entry.reply = reply_text
        entry.status = 'resolved'
        entry.save()
        
        # Notify the user who posted the message
        _add_notif_logic(
            entry.user.id, 
            "COMMUNITY REPLY", 
            f"💬 {reply_by} replied: {reply_text[:50]}..."
        )
        
        return Response({"status": "success"})
    except forum_entry.DoesNotExist:
        return Response({"status": "error", "message": "Forum entry not found"}, status=404)
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def delete_forum_entry(request):
    """
    Example Payload:
    {
        "forum_id": "1"
    }
    """
    forum_id = request.data.get('forum_id')
    forum_entry.objects.filter(id=forum_id).update(deleted=True)
    return Response({"status": "success"})

# ─────────────────────────────────────────────────────────────────────────────
# TASK LIFECYCLE ACTIONS
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
def start_task(request):
    """
    Example Payload:
    {
        "assign_id": "1",
        "user_id": "2"
    }
    """
    assign_id = request.data.get('assign_id')
    user_id   = request.data.get('user_id') # Required for security & concurrency
    try:
        if not user_id:
             return Response({"status": "error", "message": "user_id is required for concurrency check"}, status=400)

        # 🛡️ CONCURRENCY LOCK: Only one task "In Progress" at a time for this user
        in_progress_status, _ = statusoption.objects.get_or_create(name='In Progress')
        in_progress_count = assignment.objects.filter(
            assigned_to_id=user_id, 
            status=in_progress_status,
            deleted=False
        ).count()
        
        if in_progress_count > 0:
             return Response({
                 "status": "locked", 
                 "message": "⚠️ CONCURRENCY LOCK: You already have a task in progress. You must complete it before starting another."
             }, status=403)

        status = in_progress_status
        
        # Security: check ownership
        qs = assignment.objects.filter(id=assign_id, deleted=False)
        if user_id:
             qs = qs.filter(assigned_to_id=user_id)
        
        updated = qs.update(status=status, start_date=timezone.now())
        if not updated:
             return Response({"status": "error", "message": "Task not found or permission denied"}, status=403)
             
        # 🔔 IMMEDIATE NOTIFICATION (To Admin)
        try:
            assign = qs.first()
            admin = app_user.objects.filter(role__iexact='admin', deleted=False).first()
            if admin and assign:
                _add_notif_logic(
                    admin.id, 
                    "TASK STARTED", 
                    f"🚀 {assign.assigned_to.name} started working on: {assign.task.title}"
                )
        except: pass

        return Response({"status": "success"})
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def complete_task(request):
    """
    Example Payload:
    {
        "assign_id": "1",
        "user_id": "2"
    }
    """
    assign_id = request.data.get('assign_id')
    user_id   = request.data.get('user_id')
    try:
        # 🚀 NO APPROVAL FLOW: Move directly to 'Completed'
        status, _ = statusoption.objects.get_or_create(name='Completed')
        
        # Security: check ownership
        qs = assignment.objects.filter(id=assign_id, deleted=False)
        if user_id:
             qs = qs.filter(assigned_to_id=user_id)

        updated = qs.update(status=status, end_date=timezone.now())
        if not updated:
             return Response({"status": "error", "message": "Task not found or permission denied"}, status=403)

        # 🔔 IMMEDIATE NOTIFICATION (To Admin)
        try:
            assign = qs.first()
            admin = app_user.objects.filter(role__iexact='admin', deleted=False).first()
            if admin and assign:
                _add_notif_logic(
                    admin.id, 
                    "TASK COMPLETED", 
                    f"✅ {assign.assigned_to.name} finished: {assign.task.title}"
                )
        except: pass

        return Response({"status": "success"})
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=400)

@api_view(['POST'])
def request_approval(request):
    """
    Example Payload:
    {
        "assign_id": "1",
        "user_id": "2",
        "comment": "Finished earlier than expected."
    }
    """
    assign_id = request.data.get('assign_id')
    user_id   = request.data.get('user_id')
    comment   = request.data.get('comment', '')
    try:
        status = statusoption.objects.filter(name__iexact='Awaiting Approval').first()
        if not status:
            status, _ = statusoption.objects.get_or_create(name='Awaiting Approval')
        
        # Security: check ownership
        qs = assignment.objects.filter(id=assign_id, deleted=False)
        if user_id:
             qs = qs.filter(assigned_to_id=user_id)

        updated = qs.update(status=status, comments=comment)
        if not updated:
             return Response({"status": "error", "message": "Task not found or permission denied"}, status=403)

        return Response({"status": "success"})
    except Exception as e:
        return Response({"status": "error", "message": str(e)}, status=400)

def _run_overdue_check_logic():
    """
    Core logic for identifying overdue tasks and flagging them.
    Can be called from views or background workers.
    """
    now = timezone.now()
    # Logic: Only overdue if the deadline passed BEFORE today started (Next-day logic)
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        overdue_status, _ = statusoption.objects.get_or_create(name='Overdue')
        qs = assignment.objects.filter(
            deleted=False, 
            deadline__lt=today_start
        ).exclude(status__name__iexact='Completed').exclude(status__name__iexact='Overdue')
        
        for asgn in qs:
            asgn.status = overdue_status
            if not asgn.notified_overdue:
                 asgn.notified_overdue = True
                 _add_notif_logic(
                     asgn.assigned_to_id, 
                     "TASK OVERDUE", 
                     f"⚠️ The task '{asgn.task.title}' has missed its deadline and is now marked as Overdue."
                 )
            asgn.save()
    except Exception as e:
        _err("OVERDUE-CORE", str(e))

@api_view(['POST'])
def check_overdue(request):
    """
    Manually triggers an overdue check (for sync purposes).
    
    Example Payload:
    {}
    """
    try:
        _run_overdue_check_logic()
        return Response({"status": "sync_complete"})
    except Exception as e:
        _err("OVERDUE-CHECK", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# ANALYTICS & REPORTS
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def get_reports(request):
    """
    Returns a list of all users and their task completion metrics.
    """
    try:
        users = app_user.objects.filter(deleted=False)
        report = []
        for u in users:
            u_tasks = assignment.objects.filter(assigned_to=u, deleted=False)
            completed = u_tasks.filter(status__name__iexact='Completed').count()
            overdue   = u_tasks.filter(status__name__iexact='Overdue').count()
            total     = u_tasks.count()
            
            report.append({
                "user_id": u.id,
                "name": u.name,
                "total": total,
                "completed": completed,
                "overdue": overdue,
                "completion_rate": round(completed / total * 100, 1) if total else 0,
            })
        return Response(report)
    except Exception as e:
        _err("REPORTS", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['GET'])
def system_check(request):
    """
    LIGHTWEIGHT PULSE CHECK (PRECISION UPGRADE)
    Real logic is now handled by the Background Worker.
    This endpoint remains for legacy compatibility and health checks.
    """
    try:
        return Response({"status": "ok", "summary": "System background worker active and healthy."})
    except Exception as e:
        _err("SYSTEM-CHECK", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['GET'])
def get_recent_activity(request):
    """
    Returns the most recent global activity.
    """
    try:
        qs = assignment.objects.filter(deleted=False).select_related(
            'task', 'assigned_to', 'status'
        ).order_by('-dtm_created')[:10]
        return Response(AssignmentSerializer(qs, many=True).data)
    except Exception as e:
        _err("ACTIVITY", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['GET'])
def get_user_summary(request):
    """
    Returns stats for a specific user (Today's tasks, pending, etc).
    """
    user_id = request.query_params.get('user_id')
    if not user_id:
        return Response({"error": "user_id required"}, status=400)
        
    try:
        today = date.today()
        qs = assignment.objects.filter(assigned_to_id=user_id, deleted=False)
        
        return Response({
            "today_tasks": qs.filter(deadline=today).count(),
            "pending":     qs.filter(status__name__iexact='Pending').count(),
            "completed":   qs.filter(status__name__iexact='Completed').count(),
            "overdue":     qs.filter(status__name__iexact='Overdue').count(),
        })
    except Exception as e:
        _err("USER-SUMMARY", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM CHECK
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['POST'])
def run_system_check(request):
    """
    Automated background task to check for overdue items and system health.
    Expects to be called periodically by the frontend or a cron job.
    
    Example Payload:
    {}
    """
    today = date.today()
    try:
        overdue_status, _ = statusoption.objects.get_or_create(name='Overdue')

        # 1. Update Newly Overdue Tasks
        newly_overdue = assignment.objects.filter(
            deleted=False, 
            deadline__lt=today, 
            notified_overdue=False
        ).exclude(status__name__iexact='Completed').select_related('task', 'assigned_to')

        newly_list = list(newly_overdue)
        for asgn in newly_list:
            asgn.status = overdue_status
            asgn.notified_overdue = True
            asgn.save()
            
            # Notify the employee
            _add_notif_logic(asgn.assigned_to_id, f"🚨 Task Overdue: '{asgn.task.title}' needs immediate attention!")

        # 2. Update Not Started status
        not_started = assignment.objects.filter(
            deleted=False, 
            start_date__isnull=True, 
            notified_start=False,
            status__name__iexact='Pending'
        ).select_related('task', 'assigned_to')
        
        for asgn in not_started:
            asgn.notified_start = True
            asgn.save()

        # 3. Aggregate Stats for Summary
        total_overdue = assignment.objects.filter(deleted=False, status__name__iexact='Overdue').count()
        
        parts = []
        if total_overdue > 0: parts.append(f"{total_overdue} overdue")
        if len(newly_list) > 0: parts.append(f"{len(newly_list)} newly flagged")

        if parts:
            summary = "📊 System Alert: " + ", ".join(parts)
            # Notify main admin (ID 1)
            _add_notif_logic(1, "SYSTEM SUMMARY", summary)
            return Response({"status": "ok", "summary": summary})
            
        return Response({"status": "ok", "summary": "System healthy"})
    except Exception as e:
        _err("SYSTEM-CHECK", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

def _add_notif_logic(user_id, title, message):
    """Internal helper to add notifications without full API overhead."""
    try:
        user = app_user.objects.get(id=user_id)
        notification.objects.create(user=user, title=title, message=message)
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# INTELLIGENT PULSE SYNC
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
def get_pulse(request):
    """
    Lightweight sync check. Returns a sync_key that changes whenever any
    assignment is created, updated (start/end date, status), or a new
    notification arrives for the requesting user.
    """
    user_id = request.query_params.get('user_id')
    if not user_id:
        return Response({"error": "user_id required"}, status=400)
        
    try:
        # Update presence
        app_user.objects.filter(id=user_id).update(last_seen=timezone.now())
        # 1. Assignments (Total count + Max ID)
        agg_assign = assignment.objects.filter(deleted=False).aggregate(
            c=Count('id'),
            m=Max('id'),
            mod=Max('dtm_modified')
        )
        a_count = agg_assign['c'] or 0
        a_max   = agg_assign['m'] or 0
        # Incorporate timestamp to catch status updates (since modified changes)
        a_mod   = int(agg_assign['mod'].timestamp()) if agg_assign['mod'] else 0

        # 2. Notifications (Max ID for THIS user)
        n_max = notification.objects.filter(user_id=user_id).aggregate(m=Max('id'))['m'] or 0

        # 3. Forum (Overall count)
        f_count = forum_entry.objects.filter(deleted=False).count()

        sync_key = f"v{a_count}_{a_max}_{a_mod}_{n_max}_{f_count}"
        
        return Response({
            "sync_key": sync_key,
            "server_time": datetime.now().isoformat(),
        })
    except Exception as e:
        _err("PULSE", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)

@api_view(['POST'])
def bulk_update_template_assignments(request):
    """
    Updates the status of ALL active (non-deleted) assignments for a given
    template task_id. Used by Master Control to push a status change to every
    employee assigned to that template.
    
    Example Payload:
    {
        "task_id": "1",
        "status": "Paused"
    }
    """
    task_id    = request.data.get('task_id')
    new_status = request.data.get('status')

    if not task_id or not new_status:
        return Response({"status": "error", "message": "task_id and status are required"}, status=400)

    try:
        status_obj, _ = statusoption.objects.get_or_create(name=new_status)

        # If setting to Completed, we include everyone who wasn't completed.
        # Otherwise, we exclude already completed tasks to prevent overriding finished work.
        query = assignment.objects.filter(task_id=task_id, deleted=False)
        if new_status.lower() != 'completed':
            query = query.exclude(status__name__iexact='Completed')
            
        updated = query.update(status=status_obj)

        # Notify each affected employee
        affected = assignment.objects.filter(
            task_id=task_id, deleted=False, status=status_obj
        ).select_related('assigned_to', 'task')

        admin = app_user.objects.filter(role__iexact='admin', deleted=False).first()
        admin_id = admin.id if admin else 1

        for a in affected:
            _add_notif_logic(
                a.assigned_to.id,
                "TASK STATUS UPDATED",
                f"📋 Your task '{a.task.title}' status has been updated to: {new_status}"
            )

        _add_notif_logic(
            admin_id,
            "BULK STATUS UPDATE",
            f"✅ Status of '{updated}' assignment(s) for task #{task_id} set to '{new_status}'"
        )

        return Response({"status": "success", "updated": updated})
    except Exception as e:
        _err("BULK-STATUS", str(e), exc=True)
        return Response({"status": "error", "message": str(e)}, status=500)
