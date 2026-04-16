import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from tasks.models import statusoption, priorityoption, app_user, task_management, assignment

def seed():
    print("Starting database seeding...")

    # 1. Seed Statuses
    statuses = ['Pending', 'In Progress', 'Completed', 'Overdue', 'Awaiting Approval', 'inactive']
    for name in statuses:
        obj, created = statusoption.objects.get_or_create(name=name)
        if created:
            print(f"Created Status: {name}")
        else:
            print(f"Status exists: {name}")

    # 2. Seed Priorities
    priorities = ['High', 'Medium', 'Low']
    for name in priorities:
        obj, created = priorityoption.objects.get_or_create(name=name)
        if created:
            print(f"Created Priority: {name}")
        else:
            print(f"Priority exists: {name}")

    # 3. Seed Default Admin User (ID=1)
    admin_email = "admin@gmail.com"
    admin_user = app_user.objects.filter(id=1).first()
    if not admin_user:
        admin_user = app_user.objects.create(
            id=1,
            name="Admin",
            email=admin_email,
            password="admin123",
            phone="1234567890",
            role="admin",
            status="active"
        )
        print(f"Created Admin User (id=1): {admin_email}")
    else:
        print(f"Admin User (id=1) already exists: {admin_user.email}")

    # 4. Seed Sample Employees
    emp_data = [
        {"name": "John Doe", "email": "john@example.com", "phone": "9998887771"},
        {"name": "Jane Smith", "email": "jane@example.com", "phone": "9998887772"},
    ]
    for data in emp_data:
        emp, created = app_user.objects.get_or_create(
            email=data['email'],
            defaults={**data, "password": "password123", "role": "employee", "status": "active"}
        )
        if created: print(f"Created Employee: {emp.name}")

    # 5. Seed Sample Task & Assignment
    task, created = task_management.objects.get_or_create(
        title="Welcome System Check",
        defaults={
            "description": "Verify all dashboard modules are loading correctly.",
            "priority": priorityoption.objects.get(name='High'),
            "created_by": "Admin"
        }
    )
    if created: print(f"Created Task Template: {task.title}")

    # Assign to John Doe
    john = app_user.objects.get(email="john@example.com")
    assign, created = assignment.objects.get_or_create(
        task=task,
        assigned_to=john,
        defaults={
            "assigned_by": "Admin",
            "status": statusoption.objects.get(name='Pending'),
            "deadline": (timezone.now() + timedelta(days=7)).date()
        }
    )
    if created: print(f"Created Sample Assignment for John")

    print("Seeding complete!")

if __name__ == '__main__':
    from datetime import timedelta
    from django.utils import timezone
    seed()
