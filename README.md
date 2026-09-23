                                           ﷽
# themy

**themy** is a modular, wallpaper-driven desktop theming tool for Linux.

It takes a wallpaper, generates a Material-style color palette with **Matugen**, and applies that palette to the applications you choose.

The project is designed around one simple idea:

> **Modules you make the module and themy apply it**

Instead of maintaining one huge script full of application-specific logic, themy uses independent modules. Each application can have its own renderer, apply logic, backup/restore behavior, and diagnostics.

---

## Features

- 🖼️ Wallpaper-driven color generation
- 🎨 Matugen-powered Material color schemes
- 🧩 Modular application support
- 🌗 Dark/light color schemes
- 💾 Palette caching based on wallpaper content
- 🔄 Backup and restore support for modules
- 🩺 Module diagnostics through `doctor`
- 🖥️ Graphical interface
- 💻 Interactive CLI mode
- 📦 Add modules from Git repositories
- 🔒 Safety checks around module installation and execution
- 📝 The tool leaves your configs and creats is own file to control

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
        ┌────────┼────────┐────────┐
        ▼        ▼        ▼        ▼
       GTK      Qt       Yazi     other
        │        │        │        |
        └────────┼────────┘────────┘
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

```bash
git clone https://github.com/Impairon/Themy_theme_control.git
cd themy_theme_control
chmod +x install.sh
./install.sh
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
## Safe failure

If Themy cannot safely determine what it is about to modify, it should stop rather than overwrite unknown configuration.

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

## Pass the current wallpaper

For example:

```bash
themy --dark --scheme tonal-spot --color auto "$(noctalia msg wallpaper-get)"
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

