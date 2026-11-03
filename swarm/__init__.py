"""swarm — a fixed cast of reviewers over one diff.

The CLI (`swarm/swarm`) is a thin wrapper over this package:

    from swarm.api import review
    report = review("~/dev/webapp", reviewers=["code-reviewer"])
    print(report.overall, report.exit_code)
"""

from .api import (  # noqa: F401
    NothingToReview,
    Report,
    SwarmError,
    list_hosts,
    list_reviewers,
    load_config,
    resolve_target,
    review,
)

__version__ = "0.1.0"
