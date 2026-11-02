"""Isolated local release-check entry point; never cleans the main server's jobs."""
from comparison_server.app import app,jobs
from shared.settings import ROOT

jobs.root=ROOT/'temp/validation-tasks'
jobs.root.mkdir(parents=True,exist_ok=True)
