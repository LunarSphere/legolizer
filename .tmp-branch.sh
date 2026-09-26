#!/bin/bash
set -euo pipefail
cd /home/vagrant/hackathon_shared/legolizer
git fetch origin main
git checkout main
git pull origin main
git checkout -b feat/mobile-camera-image-input
git status
git log -3 --oneline
