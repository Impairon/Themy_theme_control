#!/usr/bin/env bash

Main_Dir="$HOME/.config/themy"

echo "Installing themy..."

mkdir -p "$Main_Dir"

echo "Installed themy to $Main_Dir"

insatll -m 755 themy /usr/local/bin
cp -r gui/ internals/ "$Main_Dir"

echo "Installed themy successfully"
echo "try themy and play with the gui have fun"
