import logging
import resource
import sys
import structlog
from sylus.config import config


def setup_logging() -> None:
    log_level = getattr(logging, config.log_level.upper(), logging.INFO)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.dev.set_exc_info,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(sys.stdout),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)


def get_process_rss_mb() -> float:
    """Returns process resident set size (RSS) memory in MB."""
    try:
        return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0
    except Exception:
        return 0.0


def log_memory_usage(context: str = "Startup") -> float:
    """Logs current process RSS memory and emits warning if above configurable threshold."""
    rss_mb = get_process_rss_mb()
    threshold_mb = float(config.get("memory.warning_threshold_mb", 400.0))
    logger = get_logger("sylus.memory")

    logger.info(
        f"{context} process memory usage",
        rss_mb=round(rss_mb, 2),
        threshold_mb=round(threshold_mb, 2),
    )
    if rss_mb > threshold_mb:
        logger.warning(
            f"Process memory usage ({rss_mb:.2f} MB) exceeds threshold ({threshold_mb:.2f} MB)!",
            rss_mb=round(rss_mb, 2),
            threshold_mb=round(threshold_mb, 2),
        )
    return rss_mb
