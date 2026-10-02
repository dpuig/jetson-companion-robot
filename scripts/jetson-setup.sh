#!/usr/bin/env bash
# One-time Jetson provisioning (runs ON the Jetson, needs sudo). Safe to re-run.
# From the Mac: scripts/jetson.sh setup
set -euo pipefail

ROS_DISTRO="${ROS_DISTRO:-humble}"
codename="$(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")"

echo ">> base tools"
sudo apt-get update
sudo apt-get install -y curl python3-pip \
  libportaudio2 alsa-utils v4l-utils ffmpeg
sudo usermod -aG audio,video "$USER"   # mic/camera access without sudo (re-login to apply)

if [[ ! -f /etc/apt/sources.list.d/ros2.sources && ! -f /etc/apt/sources.list.d/ros2.list ]]; then
  echo ">> ROS 2 apt source"
  sudo apt-get install -y software-properties-common
  sudo add-apt-repository -y universe
  ver="$(curl -fsSL https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest \
         | grep -F '"tag_name"' | awk -F'"' '{print $4}')"
  curl -fsSL -o /tmp/ros2-apt-source.deb \
    "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ver}/ros2-apt-source_${ver}.${codename}_all.deb"
  sudo dpkg -i /tmp/ros2-apt-source.deb
  sudo apt-get update
fi

echo ">> ROS 2 $ROS_DISTRO + colcon"
sudo apt-get install -y "ros-$ROS_DISTRO-ros-base" ros-dev-tools python3-colcon-common-extensions
[[ -f /etc/ros/rosdep/sources.list.d/20-default.list ]] || sudo rosdep init
rosdep update

echo ">> python tools (user site-packages)"
python3 -m pip install --user --upgrade debugpy

echo ">> companion: finish AI setup (models/builds are skipped if already done)"
bash "$(dirname "$0")/jetson-ai-setup.sh"

echo ">> done"
