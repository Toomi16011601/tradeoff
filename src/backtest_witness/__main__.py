"""Keep the original module command available after the Tradeoff rename."""

from tradeoff.cli import main

raise SystemExit(main())
