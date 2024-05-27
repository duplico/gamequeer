#!/bin/bash

curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.7/install.sh | bash

source $HOME/.bashrc

nvm install 20

# For Langium:
# npm i -g yo generator-langium
