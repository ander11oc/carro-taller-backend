from fastapi import HTTPException, status


Action = str
ModuleName = str
Role = str

ALL_MODULES = {
    "dashboard",
    "alerts",
    "vehicles",
    "tires",
    "retired-tires",
    "retired-tire-conditions",
    "tire-brand-designs",
    "operation-companies",
    "fuel-logs",
    "inventory",
    "documents",
    "maintenance",
    "portal",
}

READ_ALL = {module: {"read"} for module in ALL_MODULES}

ROLE_PERMISSIONS: dict[Role, dict[ModuleName, set[Action]]] = {
    "admin": {
        module: {"read", "create", "update", "delete", "import"}
        for module in ALL_MODULES
    },
    "planner": {
        **READ_ALL,
        "maintenance": {"read", "create", "update", "delete"},
        "documents": {"read", "create", "update"},
        "inventory": {"read", "create", "update"},
        "fuel-logs": {"read", "create", "update"},
        "tires": {"read", "create", "update"},
    },
    "mechanic": {
        "dashboard": {"read"},
        "alerts": {"read"},
        "vehicles": {"read", "update"},
        "tires": {"read", "create", "update"},
        "fuel-logs": {"read", "create"},
        "inventory": {"read", "update"},
        "documents": {"read"},
        "maintenance": {"read", "update"},
    },
    "viewer": READ_ALL,
    "client": {
        "dashboard": {"read"},
        "alerts": {"read"},
        "documents": {"read"},
        "maintenance": {"read"},
        "portal": {"read", "create"},
    },
}


def can_access_module(role: str, module: str, action: str) -> bool:
    return action in ROLE_PERMISSIONS.get(role, {}).get(module, set())


def require_module_action(user: dict, module: str, action: str) -> None:
    role = user.get("role", "viewer")
    if can_access_module(role, module, action):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail=f"{role} cannot {action} {module}",
    )
