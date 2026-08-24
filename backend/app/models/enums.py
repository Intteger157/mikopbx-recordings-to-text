import enum


class UserRole(str, enum.Enum):
    SUPERADMIN = "SUPERADMIN"
    MANAGER = "MANAGER"
    USER = "USER"


class TranscriptionStatus(str, enum.Enum):
    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
