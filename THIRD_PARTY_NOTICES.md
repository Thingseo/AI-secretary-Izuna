# Third-party components

The Windows portable distribution includes unmodified binaries from these upstream packages:

- **CPython 3.12.10 embedded, Windows x64.** Python Software Foundation and contributors. Python license text: `runtime/LICENSE.txt`. Download: https://www.python.org/ftp/python/3.12.10/ . Source: https://www.python.org/downloads/source/ .
- **PySide6 Essentials / Qt 6.8.3** and **Shiboken6 6.8.3**, Windows x64 ABI3 wheels. The Qt Company and contributors. Upstream package metadata and bundled license files are retained in `runtime/Lib/site-packages/*dist-info/`. The open source bindings are available under LGPLv3/GPLv3 terms; Qt components and third-party dependencies retain their respective terms. Relevant full license texts are also included under `licenses/`. Upstream: https://pypi.org/project/PySide6-Essentials/6.8.3/ and https://pypi.org/project/shiboken6/6.8.3/ . Corresponding source releases: https://download.qt.io/official_releases/QtForPython/pyside6/PySide6-6.8.3-src/ and https://download.qt.io/archive/qt/6.8/6.8.3/ .
- Microsoft runtime DLLs included by the official CPython/Qt packages are retained with their upstream packages.

Qt libraries are dynamically loaded and have not been modified. Users can replace them with compatible builds. No application-level restriction is imposed on reverse engineering for debugging modifications to LGPL libraries. See the retained upstream notices for exact component-specific terms.

The original application code is provided under the MIT license. The supplied character artwork is not part of that license. No claim of ownership or affiliation with the character rights holders or the illustrator is made.

The portable runtime is a local vendored dependency bundle: updating Python/Qt means rebuilding it from official upstream packages. `BUILD_EXE.bat` is an optional developer route and does not install anything until explicitly run.
