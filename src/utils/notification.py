"""User notification system for Lyra.

This module has been split into focused submodules:

- `intervention_types`: Enums and data classes (InterventionStatus, InterventionType, InterventionResult)
- `intervention_manager`: Intervention management and user notifications
- `batch_notification`: Batch notification manager for CAPTCHA/auth queues
- `intervention_queue`: Authentication queue management with database persistence

Import directly from the submodules. This file is kept for documentation only.
"""

# This module has been split. Import from submodules:
# - from src.utils.intervention_types import InterventionStatus, InterventionType, InterventionResult
# - from src.utils.intervention_manager import InterventionManager, notify_user, notify_domain_blocked, get_intervention_manager
# - from src.utils.batch_notification import BatchNotificationManager, notify_target_queue_empty
# - from src.utils.intervention_queue import InterventionQueue, get_intervention_queue
