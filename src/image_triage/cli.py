"""Command line interface, generated from the configuration parameters."""

import sys
from logging import Logger

from config_cli_gui.cli import CliGenerator
from config_cli_gui.config import ConfigManager
from config_cli_gui.logging import initialize_logging

from image_triage import pipeline
from image_triage.config import ImageTriageConfig


def run_selection(config: ConfigManager, logger: Logger) -> int:
    logger.setLevel(config.app.log_level.value)
    pipeline.run(config, logger)
    return 0


def main() -> int:
    config = ImageTriageConfig()
    logger_manager = initialize_logging(
        log_level=config.app.log_level.value,
        enable_file_logging=False,
        enable_console_logging=True,
    )
    cli = CliGenerator(config_manager=config, app_name="image-triage")
    return cli.run_cli(
        main_function=run_selection,
        description="Analyze photos, group similar shots, rate them (1-5 stars), export the best.",
        logger=logger_manager.get_logger("cli"),
    )


if __name__ == "__main__":
    sys.exit(main())
