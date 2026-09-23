                                 ﷽
# themy

**themy** is a modular, wallpaper-driven desktop theming tool for Linux.

It takes a wallpaper, generates a Material-style color palette with **Matugen**, and applies that palette to the applications you choose.

The project is designed around one simple idea:

> **Themy owns the theme layer, while your applications keep their normal configuration.**

Instead of maintaining one huge script full of application-specific logic, themy uses independent modules. Each application can have its own renderer, apply logic, backup/restore behavior, and diagnostics.

---

## Features

- 🖼️ Wallpaper-driven color generation
- 🎨 Matugen-powered Material color schemes
- 🧩 Modular application support
- 🖥️ Qt theming
- 🪟 GTK theming
- 📁 Yazi theming
- 🐱 Kitty theming
- 🌗 Dark/light color schemes
- 💾 Palette caching based on wallpaper content
- 🔄 Backup and restore support for modules
- 🩺 Module diagnostics through `doctor`
- 🖥️ Graphical interface
- 💻 Interactive CLI mode
- 📦 Add modules from Git repositories
- 🔒 Safety checks around module installation and execution
- 🧹 Keeps generated theme files separate from normal user configuration

---

# How it works

The basic pipeline is:

```text
             wallpaper
                 │
                 ▼
        ┌─────────────────┐
        │     Matugen     │
        └────────┬────────┘
                 │
                 ▼
             palette
                 │
        ┌────────┼────────┐
        ▼        ▼        ▼
       GTK      Qt       Yazi
        │        │        │
        └────────┼────────┘
                 ▼
          application theme
```

Themy does not try to make every application understand Matugen directly.

Instead, Matugen produces the palette and each module translates that palette into the format required by its application.

For example:

```text
Matugen palette
      │
      ├── GTK module  → CSS
      ├── Qt module   → qt5ct / qt6ct colors.conf
      ├── Yazi module → flavor.toml
      └── Kitty       → kitty.conf
```

This makes adding another application much easier: add another module instead of modifying the entire theming engine.

---

# Installation

The executable can be installed globally:

```text
/usr/local/bin/themy
```

Themy keeps its runtime files in your user configuration directory:

```text
~/.config/themy/
```

A typical installation looks like:

```text
~/.config/themy/
├── gui/
│   └── themy-gui.py
├── internals/
├── templates/
└── modules/
```

The executable itself does **not** depend on the directory from which you launch it.

So this works:

```bash
cd ~/Downloads
themy
```

as well as:

```bash
cd ~/projects
themy
```

---

# Requirements

Themy is intended for a Linux desktop environment.

The core dependency is:

- `bash`
- `matugen`

The graphical interface requires:

- Python 3
- PyQt6

Application-specific dependencies are handled by their respective modules.

Qt6 itself is **not required** for the Qt module to exist. The module only uses Qt6-related configuration when the corresponding Qt6/qt6ct environment is actually available.

---

# First run

Start themy:

```bash
themy
```

By default this opens the graphical interface.

Themy may ask you to choose your wallpaper directory on first use.

The selected directory is shared between the GUI and CLI through Themy's state directory.

---

# CLI

## Open the GUI

```bash
themy
```

## Interactive CLI

```bash
themy -i
```

This mode provides an interactive terminal interface for selecting wallpapers, schemes, and modules.

---

## Apply a wallpaper

```bash
themy apply /path/to/wallpaper.jpg
```

The wallpaper must be an absolute path to a readable regular file.

Example:

```bash
themy apply /home/user/Pictures/wallpapers/cat.jpg
```

---

## Show the current wallpaper

```bash
themy current-wallpaper
```

This reads the wallpaper information known to Themy/DankMaterialShell session state.

It can be useful for scripting.

For example:

```bash
themy --dark --scheme tonal-spot --color auto "$(themy current-wallpaper)"
```

---

## Show status

```bash
themy status
```

Displays information about the current theming state and enabled modules.

---

## Check the installation

```bash
themy doctor
```

`doctor` is intended to help diagnose missing dependencies, configuration problems, and module issues.

---

## List modules

```bash
themy modules
```

This shows the modules currently available to Themy.

---

# Module system

The module system is the heart of Themy.

Instead of having application-specific code inside the main script, every application is represented by its own module.

A runtime module looks roughly like:

```text
~/.config/themy/modules/
└── yazi/
    ├── module.conf
    ├── render
    ├── apply
    ├── backup
    ├── restore
    ├── doctor
    └── templates/
```

The exact files can vary depending on the module.

The important principle is:

```text
themy
  │
  └── module
       ├── render
       ├── apply
       ├── backup
       ├── restore
       └── doctor
```

The main engine does not need to know the internal implementation of every application.

---

# Module lifecycle

A normal theme generation follows this pattern:

```text
1. Select wallpaper
        │
        ▼
2. Generate / load palette
        │
        ▼
3. Ask enabled modules to render
        │
        ▼
4. Backup existing application state
        │
        ▼
5. Apply generated theme
```

A module therefore has a clear separation between:

### Render

Generate the application's theme from the Matugen palette.

### Apply

Install or activate the generated theme.

### Backup

Preserve the user's existing configuration before Themy changes it.

### Restore

Return the application to its previous state.

### Doctor

Check whether the module can work correctly on the current system.

---

# Adding modules

Themy can install modules from Git repositories.

The GUI's **Add Program** workflow asks for a repository URL and installs the module into:

```text
~/.config/themy/modules/<module-name>
```

A module must contain at least:

```text
module.conf
render
apply
```

Additional hooks such as:

```text
backup
restore
doctor
```

can be provided when needed.

---

# Module safety

Because modules contain executable code, Themy treats them as untrusted input during installation.

Themy validates module names and module trees before installing them.

Module names must follow:

```text
[A-Za-z0-9][A-Za-z0-9._-]{0,63}
```

The module tree is also checked for unsafe symbolic links.

The GUI archive installer rejects unsafe archive entries such as:

- absolute paths
- `..` path traversal
- symbolic links
- hard links
- device entries

Extracted files are also subject to size limits.

The goal is to prevent a module archive from escaping its intended installation directory.

---

# Palette caching

Generating a palette does not need to happen repeatedly for the exact same wallpaper.

Themy caches palettes using the wallpaper's SHA-256 hash.

The GUI cache is stored under:

```text
~/.config/themy/cache/palettes/
```

A cached palette is associated with:

```text
wallpaper hash
+
dark/light mode
```

Conceptually:

```text
wallpaper
   │
   ▼
SHA-256
   │
   ▼
cache/<hash>/<mode>.json
```

If the same wallpaper is used again with the same mode, Themy can reuse the cached palette instead of recalculating it.

---

# GTK

The GTK module generates a Themy-owned GTK theme rather than modifying the system's installed theme directly.

The general structure is:

```text
installed GTK theme
        │
        ▼
copy to Themy-owned theme
        │
        ▼
generate Themy colors
        │
        ▼
apply Themy widget overrides
```

The generated theme is stored in the user's data directory.

Themy then activates the generated GTK theme.

This keeps the system-installed theme untouched.

The GTK theme contains semantic roles for things such as:

- accent colors
- destructive/error states
- success/warning states
- windows
- views
- header bars
- cards
- dialogs
- popovers
- sidebars
- selections
- borders
- legacy GTK aliases

The module also supports additional widget styling through its widget template.

---

# Qt

The Qt module generates a Themy-owned Qt color scheme.

Depending on what is installed/configured, it can generate:

```text
qt5ct/colors/themy.conf
```

and/or:

```text
qt6ct/colors/themy.conf
```

The Qt color scheme contains semantic sections for areas such as:

```text
[ColorScheme]

[Colors:Button]

[Colors:Complementary]

[Colors:Header]

[Colors:HeaderInactive]

[Colors:Selection]

[Colors:Tooltip]

[Colors:View]

[Colors:Window]

[WM]
```

The generated configuration contains semantic foreground, background, selection, link, focus, hover, and state colors.

Qt6 is optional. If Qt6/qt6ct is not installed, Themy does not treat that as an error requiring Qt6 to be installed.

---

# Yazi

The Yazi module generates a Themy flavor based on the application's theme structure.

The generated flavor is installed as:

```text
~/.config/yazi/flavors/themy.yazi/
```

and Themy selects the generated flavor through Yazi's theme configuration.

The Yazi module is intentionally designed around semantic color substitution rather than replacing the entire theme structure with a simplified custom theme.

The default background is allowed to remain transparent/reset so the terminal background can remain visible.

This is particularly useful when the terminal itself is using a wallpaper or transparent background.

Themy also refuses to overwrite a `theme.toml` that it does not own.

---

# Kitty

The Kitty module generates:

```text
~/.config/kitty/theme.conf
```

and ensures the main Kitty configuration includes it:

```kitty
include theme.conf
```

Themy manages the theme file while the user keeps their normal Kitty configuration in:

```text
~/.config/kitty/kitty.conf
```

Themy deliberately does **not** manage font settings.

For example, the user can keep:

```kitty
font_family ...
font_size ...
```

in their own `kitty.conf`.

Themy focuses on colors and theme-related visual settings.

---

# Configuration and state

Themy follows the XDG directory layout.

The main configuration directory is:

```text
$XDG_CONFIG_HOME/themy
```

or, when `XDG_CONFIG_HOME` is not set:

```text
~/.config/themy
```

The runtime state directory follows:

```text
$XDG_STATE_HOME/themy
```

or:

```text
~/.local/state/themy
```

The data directory follows:

```text
$XDG_DATA_HOME
```

or:

```text
~/.local/share
```

This keeps configuration, generated data, and runtime state separated.

---

# Wallpaper directory

Themy remembers the wallpaper directory selected by the user.

The state is shared between the GUI and CLI.

When a wallpaper is selected, Themy can update the remembered directory to the wallpaper's parent directory.

This means you do not need to configure the wallpaper directory independently for the GUI and command line.

---

# Backups and restoration

Modules that modify existing application configuration can provide backup and restore hooks.

The intended workflow is:

```text
existing configuration
        │
        ▼
      backup
        │
        ▼
  Themy-generated theme
```

and later:

```text
Themy-generated theme
        │
        ▼
      restore
        │
        ▼
existing configuration
```

Themy therefore does not need to permanently replace the user's original application configuration.

---

# GUI

The graphical interface provides the main interactive workflow.

The GUI is organized around:

- wallpapers
- color schemes
- programs/modules
- application state
- theme application

The GUI also provides the module installation workflow.

The visual design is intended to be:

- clean
- dark
- rounded
- responsive
- easy to scan
- consistent with the generated desktop theme

The GUI is a frontend to the same theming system rather than a separate theming implementation.

---

# Design philosophy

Themy follows a few principles.

## 1. Modules instead of one giant script

Application-specific logic belongs in the application module.

This makes it possible to improve Yazi without rewriting GTK or Qt support.

---

## 2. Themy owns generated files

Generated files should be clearly separated from user configuration whenever possible.

For example:

```text
Kitty:
    kitty.conf       → user
    theme.conf       → Themy
```

This makes it clear which file the user should edit and which file Themy controls.

---

## 3. Semantic colors

Themy should not blindly replace every color with the same palette value.

Applications have different semantic roles.

For example:

```text
primary
surface
surface_container
on_surface
outline
error
tertiary
selection
```

A module maps those semantic roles into the application's own theme format.

---

## 4. Preserve application structure

Themy should work with the application's existing theme architecture instead of replacing it with a minimal approximation.

This is especially important for complex themes such as GTK and Yazi.

---

## 5. Transparency matters

Where an application supports it, Themy should allow the terminal/background to remain visible instead of forcing an opaque background everywhere.

---

## 6. Safe failure

If Themy cannot safely determine what it is about to modify, it should stop rather than overwrite unknown configuration.

---

# Project layout

The development tree is organized roughly as:

```text
.
├── gui/
├── internals/
├── templates/
└── themy
```

The installed runtime mirrors the same separation:

```text
~/.config/themy/
├── gui/
├── internals/
├── templates/
└── modules/
```

### `themy`

The main orchestration layer.

Responsible for:

- command handling
- wallpaper validation
- Matugen execution
- palette generation/loading
- module discovery
- module lifecycle
- state handling

### `gui/`

The graphical frontend.

### `internals/`

Shared implementation details and helper functionality.

### `templates/`

Bundled module templates used when bootstrapping the runtime module directory.

### `modules/`

The actual runtime application modules.

---

# Typical workflow

A normal user workflow can be as simple as:

```bash
themy
```

Choose:

```text
Wallpaper
   ↓
Color scheme
   ↓
Programs
   ↓
Apply
```

Or from the terminal:

```bash
themy -i
```

For scripting:

```bash
themy apply /absolute/path/to/wallpaper.png
```

---

# Troubleshooting

Start with:

```bash
themy doctor
```

Then inspect available modules:

```bash
themy modules
```

If a module is behaving unexpectedly, check that its runtime directory exists:

```text
~/.config/themy/modules/<module>
```

For GUI problems, make sure Python and PyQt6 are available.

For palette-generation problems, verify that Matugen is installed:

```bash
matugen --version
```

For application-specific problems, the module's `doctor` command is the appropriate place to start.

---

# Development

A module can be developed independently from the rest of Themy.

For example:

```text
modules/
└── yazi/
    ├── module.conf
    ├── render
    ├── apply
    ├── backup
    ├── restore
    ├── doctor
    └── templates/
```

This means a developer can focus on:

```text
yazi/
```

without changing the Qt, GTK, or Kitty implementations.

That modularity is intentional.

---

# Adding another application

To add a new application:

1. Create a module directory.
2. Add `module.conf`.
3. Implement `render`.
4. Implement `apply`.
5. Add `backup`/`restore` if the application requires existing configuration changes.
6. Add `doctor` if useful.
7. Add templates for the application's theme format.
8. Test the generated output independently.
9. Install the module into the runtime module directory.

The core Themy engine should not need application-specific changes unless the module requires a new shared capability.

---

# Philosophy in one sentence

**Themy turns one wallpaper into a coordinated desktop theme while keeping application-specific theming modular, generated, and safely separated from the user's configuration.**

---

## Status

Themy is actively developed.

Current core application targets are:

- GTK
- Qt
- Yazi
- Kitty

Additional applications can be added later as independent modules.
