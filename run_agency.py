#!/usr/bin/env python3
"""Main CLI entrypoint for Freelancer Agency system."""
import asyncio
import sys
from src.app import AgencyApplication


def main():
    app = AgencyApplication()

    if "--mcp" in sys.argv:
        # Run in Model Context Protocol STDIO mode
        app.run_mcp_stdio()
    elif "--scan-once" in sys.argv:
        # Run a single discovery and scoring batch
        stats = app.scan_and_score()
        print(f"Scan finished: {stats}")
    else:
        # Run full background production service
        try:
            asyncio.run(app.run_server())
        except KeyboardInterrupt:
            print("\nShutting down Freelancer Agency gracefully...")


if __name__ == "__main__":
    main()
