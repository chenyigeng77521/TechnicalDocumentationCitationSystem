#!/bin/bash

current_path=$(pwd)
echo $current_path

bash "$current_path/stopAll.sh"
bash "$current_path//devStart.sh"

