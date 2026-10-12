import os
import re
import subprocess
from pathlib import Path

import info
import utils
from Blueprints.CraftPackageObject import CraftPackageObject
from Packager.AppxPackager import AppxPackager
from Packager.NullsoftInstallerPackager import NullsoftInstallerPackager

# The product name, in one place, because three different things have to
# agree about it or the package breaks in ways that do not mention names:
#
#   * files365.json in the desktop repo (applicationName), which
#     admin/theme_patcher.py reads when it renames the built artefacts,
#   * the bundle path this blueprint hands the macOS packager, which must
#     match what the patcher renamed the bundle TO,
#   * the executable name, which the patcher derives from the application
#     name as name.lower().replace(" ", "_") on Windows and Linux, and
#     uses verbatim on macOS.
#
# Upstream keeps these consistent by deriving them all from buildBeta.
# This fork derives them from here. If files365.json and this constant
# ever disagree, the macOS job fails at "Checking for absolute library
# paths in package" -- the packager looking for a bundle the patcher
# named something else. See DO-598.
FILES365_APPLICATION_NAME = "Files365"

# The theme the patcher applies, relative to the desktop repo's source
# directory. Upstream applies beta.json only when buildBeta is set; this
# fork always applies its own, because an unbranded Files365 build is not
# a thing we ever want to ship by accident.
FILES365_THEME_FILE = "files365.json"


class subinfo(info.infoclass):
    def registerOptions(self):
        self.options.dynamic.registerOption("buildNumber", "")
        self.options.dynamic.registerOption("enableCrashReporter", False)
        self.options.dynamic.registerOption("enableAppImageUpdater", False)
        self.options.dynamic.registerOption("enableAutoUpdater", False)
        self.options.dynamic.registerOption("enableOpenVFS", False)
        self.options.dynamic.registerOption("forceAsserts", False)
        self.options.dynamic.registerOption("buildBeta", False)

    def setTargets(self):
        self.svnTargets["main"] = "https://github.com/opencloud-eu/desktop.git|main"
        self.defaultTarget = "main"

        # Files365 fork. Every name below must agree with files365.json in
        # the desktop repo, because admin/theme_patcher.py renames the
        # built artefacts to whatever THAT file says and this blueprint
        # tells the packager where to find them. Upstream keeps the two
        # sides consistent by deriving both from buildBeta; we derive both
        # from one product name instead. See DO-598.
        self.description = "Files365 Desktop"
        self.displayName = FILES365_APPLICATION_NAME
        self.webpage = "https://files365.io"

    def setDependencies(self):
        self.buildDependencies["craft/craft-blueprints-opencloud"] = None
        self.buildDependencies["dev-utils/cmake"] = None
        self.buildDependencies["kde/frameworks/extra-cmake-modules"] = None

        self.runtimeDependencies["opencloud/libre-graph-api-cpp-qt-client"] = None
        self.runtimeDependencies["libs/zlib"] = None
        self.runtimeDependencies["libs/sqlite"] = None
        if CraftCore.compiler.isWindows:
            self.runtimeDependencies["dev-utils/snoretoast"] = None

        self.runtimeDependencies["libs/qt/qtbase"] = None
        self.runtimeDependencies["libs/qt/qttranslations"] = None
        self.runtimeDependencies["libs/qt/qtsvg"] = None
        self.runtimeDependencies["libs/qt/qtimageformats"] = None
        self.runtimeDependencies["libs/qt/qtdeclarative"] = None
        if CraftCore.compiler.isLinux:
            self.runtimeDependencies["libs/qt/qtwayland"] = None
            if self.options.dynamic.enableOpenVFS:
                self.runtimeDependencies["opencloud/openvfs"] = None

        self.runtimeDependencies["qt-libs/qtkeychain"] = None
        self.runtimeDependencies["libs/kdsingleapplication"] = None

        if self.options.dynamic.enableAutoUpdater:
            self.runtimeDependencies["libs/sparkle"] = None
            if self.options.dynamic.enableAppImageUpdater:
                self.runtimeDependencies["libs/libappimageupdate"] = None

        if self.options.dynamic.enableCrashReporter:
            self.runtimeDependencies["opencloud/libcrashreporter-qt"] = None
            self.buildDependencies["dev-utils/breakpad"] = None
            self.buildDependencies["dev-utils/symsorter"] = None

        if self.options.dynamic.buildBeta:
            self.buildDependencies["python-modules/pillow"] = None


from Package.CMakePackageBase import *


class Package(CMakePackageBase):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.subinfo.options.fetch.checkoutSubmodules = True

        if self.subinfo.options.dynamic.enableCrashReporter:
            self.subinfo.options.configure.args += ["-DWITH_CRASHREPORTER=ON"]
        if self.subinfo.options.dynamic.enableAutoUpdater:
            self.subinfo.options.configure.args += ["-DWITH_AUTO_UPDATER=ON"]
        if self.subinfo.options.dynamic.enableAppImageUpdater:
            self.subinfo.options.configure.args += ["-DWITH_APPIMAGEUPDATER=ON"]
        if self.subinfo.options.dynamic.enableOpenVFS:
            self.subinfo.options.configure.args += ["-DVIRTUAL_FILE_SYSTEM_PLUGINS=off;cfapi;openvfs"]
        if self.subinfo.options.dynamic.forceAsserts:
            self.subinfo.options.configure.args += ["-DFORCE_ASSERTS=ON"]
        if self.subinfo.options.dynamic.buildNumber:
            self.subinfo.options.configure.args += [f"-DMIRALL_VERSION_BUILD={self.subinfo.options.dynamic.buildNumber}"]
        self.subinfo.options.configure.args += [f"-DBETA_CHANNEL_BUILD={self.subinfo.options.dynamic.buildBeta.asOnOff}"]

    @property
    def applicationExecutable(self):
        # Must match what theme_patcher.py renames the binaries to:
        # applicationName.lower() with spaces as underscores. Returning
        # upstream's "opencloud" here would leave Windows shortcuts, the
        # cmd alias and the autostart entry all pointing at a file the
        # patcher has already renamed away.
        return FILES365_APPLICATION_NAME.lower().replace(" ", "_")

    def buildNumber(self):
        if self.subinfo.options.dynamic.buildNumber:
            return self.subinfo.options.dynamic.buildNumber
        return super().buildNumber()

    def dumpSymbols(self) -> bool:
        dest = self.archiveDebugDir() / "symbols"
        utils.cleanDirectory(dest)
        allowError = None
        if CraftCore.compiler.isWindows:
            skipDumpPattern = r"icu\d\d\.dll|asprintf-0\.dll"
            if CraftCore.compiler.isWindows:
                for package in ["libs/runtime", "libs/d3dcompiler", "libs/gettext"]:
                    dbPackage = CraftCore.installdb.getInstalledPackages(CraftPackageObject.get(package))
                    if dbPackage:
                        files = dbPackage[0].getFiles()
                        skipDumpPattern += "|" + "|".join([re.escape(Path(x[0]).name) for x in files])
            allowError = re.compile(skipDumpPattern)
        else:
            # libs/qt6/qtbase installs .o files...
            # executing command: /drone/src/linux-64-gcc/dev-utils/bin/symsorter --compress --compress --output /drone/src/linux-64-gcc/build/opencloud/opencloud-client/archive-dbg/symbols /drone/src/linux-64-gcc/qml/Qt/test/controls/objects-RelWithDebInfo/QuickControlsTestUtilsPrivate_resources_1/.rcc/qrc_qmake_Qt_test_controls.cpp.o /drone/src/linux-64-gcc/qml/Qt/test/controls/objects-RelWithDebInfo/QuickControlsTestUtilsPrivate_resources_1/.rcc/qrc_qmake_Qt_test_controls.cpp.o.debug
            #
            # Sorting debug information files
            #
            # qrc_qmake_Qt_test_controls.cpp.o (rel, x86_64) -> /drone/src/linux-64-gcc/build/opencloud/opencloud-client/archive-dbg/symbols/00/0000e90000000000000000009f79900/executable
            #
            # error: failed to process file qrc_qmake_Qt_test_controls.cpp.o.debug
            #
            #   caused by failed to generate debug identifier
            allowError = re.compile(r".*\.o")

        for binaryFile in utils.filterDirectoryContent(
            self.archiveDir(), whitelist=lambda x, root: utils.isBinary(os.path.join(root, x)), blacklist=lambda x, root: True
        ):
            binaryFile = Path(binaryFile)
            # Assume all files are installed and the symbols are located next to the binary
            # TODO:
            installedBinary = CraftCore.standardDirs.craftRoot() / binaryFile.relative_to(self.archiveDir())
            if not installedBinary.exists():
                CraftCore.log.warning(f"{installedBinary} does not exist")
                return False

            if CraftCore.compiler.isWindows:
                symbolFile = Path(f"{installedBinary}.pdb")
                if not symbolFile.exists():
                    pdb = utils.getPDBForBinary(installedBinary)
                    if pdb:
                        symbolFile = installedBinary.parent / utils.getPDBForBinary(installedBinary).name
            elif CraftCore.compiler.isMacOS:
                debugInfoPath = installedBinary
                bundleDir = list(filter(lambda x: x.name.endswith(".framework") or x.name.endswith(".app"), debugInfoPath.parents))
                if bundleDir:
                    debugInfoPath = bundleDir[-1]
                debugInfoPath = Path(f"{debugInfoPath}.dSYM/Contents/Resources/DWARF/") / installedBinary.name
                if debugInfoPath.exists():
                    symbolFile = debugInfoPath
            elif CraftCore.compiler.isUnix:
                symbolFile = Path(f"{installedBinary}.debug")

            if not symbolFile.exists():
                if allowError and allowError.match(binaryFile.name):
                    # ignore errors in files matching allowError
                    continue
                CraftCore.log.warning(f"{symbolFile} does not exist")
                return False
            if not utils.system(["symsorter", "--compress", "--compress", "--output", dest, installedBinary, symbolFile]):
                if allowError and allowError.match(binaryFile.name):
                    # ignore errors in files matching allowError
                    CraftCore.log.warning(f"Ignoring error for {binaryFile.name}")
                    continue
                return False
        return True

    def openCloudVersion(self, withSuffix: bool = True) -> str:
        versionFile = self.sourceDir() / "VERSION.cmake"
        if not versionFile.exists():
            CraftCore.log.warning(f"Failed to find {versionFile}")
            return None

        print_var_script = os.path.join(self.blueprintDir(), "print-var.cmake")

        def get_var(name) -> str:
            command = ["cmake", f"-DTARGET_SCRIPT={os.path.basename(versionFile)}", f"-DTARGET_VAR={name}"]

            if self.subinfo.options.dynamic.buildNumber:
                command.append(f"-DMIRALL_VERSION_BUILD={self.subinfo.options.dynamic.buildNumber}")

            if not withSuffix:
                command += ["-DMIRALL_VERSION_SUFFIX="]

            command += ["-P", print_var_script]
            value = subprocess.check_output(
                command,
                cwd=os.path.dirname(versionFile),
                # make sure this call returns str instead of bytes
                universal_newlines=True,
            )
            value = value.strip()
            assert value, f"{name} empty"
            return value

        version_str = get_var("MIRALL_VERSION_STRING")

        print(f"*** version string fetched with CMake: {version_str} ***")

        return version_str

    def createPackage(self):
        self.blacklist_file.append(os.path.join(self.blueprintDir(), "blacklist.txt"))
        # Not derived from buildBeta: the patcher renames to
        # FILES365_APPLICATION_NAME either way, so appname -- and the
        # apppath built from it below -- has to say the same.
        self.defines["appname"] = FILES365_APPLICATION_NAME
        self.defines["desktopFile"] = self.applicationExecutable
        self.defines["appimage_native_package_name"] = f'{self.applicationExecutable.lower().replace("_", "-")}-desktop'
        self.defines["apppath"] = "Applications/KDE/" + self.defines["appname"] + ".app"
        # Shown in Windows installer metadata and the Programs list.
        # Files365 rather than the legal entity, per the branding
        # direction of 12/10/2026 -- the one place the company name still
        # appears is the code signature, which names the certificate
        # holder and is not a build setting.
        self.defines["company"] = "Files365"

        exePath = Path(f"{self.applicationExecutable}{CraftCore.compiler.executableSuffix}")
        if isinstance(self, (NullsoftInstallerPackager, AppxPackager)):
            exePath = Path(f"bin/{exePath}")
        self.defines["shortcuts"] = [
            {
                "name": self.subinfo.displayName,
                "target": str(exePath),
                "description": self.subinfo.description,
                "appId": "eu.opencloud.desktopclient",
            }
        ]
        self.defines["icon"] = self.buildDir() / "src/gui/opencloud.ico"
        self.defines["pkgproj"] = self.archiveDir() / "OpenCloudAssets/macosx.pkgproj"
        if CraftPackageObject.get("dev-utils/linuxdeploy-plugin-native-packages").isInstalled:
            self.defines["appimage_extra_output"] = ["native_packages"]
        ver = self.openCloudVersion()
        if ver:
            if isinstance(self, (AppxPackager)):
                # The Microsoft Store requires a version number in the format of X.Y.0.0
                # so we skip the suffix
                self.defines["version"] = self.openCloudVersion(False)
                self.defines["icon_png_44"] = self.archiveDir() / "OpenCloudAssets/44-opencloud-icon-ms.png"
                self.defines["icon_png"] = self.archiveDir() / "OpenCloudAssets/150-opencloud-icon-ms.png"
                # this one would also require us to set a 310x150 icon
                # self.defines["icon_png_310x310"] = self.sourceDir() / "src/resources/theme/colored/310-opencloud-icon-ms.png"
                cmdPath = exePath.parent / f"{exePath.stem}cmd.exe"
                self.defines["alias_executable"] = str(cmdPath)
                self.defines["alias"] = cmdPath.name
                # autostart
                self.defines["startup_task"] = str(exePath)

                self.defines["additional_xmlns"] = """xmlns:desktop3="http://schemas.microsoft.com/appx/manifest/desktop/windows10/3"\n"""
                self.defines[
                    "extensions"
                ] = """<desktop3:Extension Category="windows.cloudFiles"><desktop3:CloudFiles></desktop3:CloudFiles></desktop3:Extension>"""
            else:
                self.defines["version"] = ver
        # the filter is executed before the files are patched so the name is always opencloud
        self.addExecutableFilter(r"(bin|libexec)/(?!(opencloud|snoretoast|openvfsfuse)).*")
        # always keep our assets, regardless of any blacklist
        self.addWhitelistFilter(lambda fileName, root: utils.regexFileFilter(fileName, root, [re.compile(r"^OpenCloudAssets/")]))
        self.ignoredPackages += ["binary/mysql"]
        if not CraftCore.compiler.isLinux:
            self.ignoredPackages += ["libs/dbus"]
        return super().createPackage()

    def preArchiveMove(self):
        if self.subinfo.options.dynamic.enableCrashReporter:
            if not self.dumpSymbols():
                return False
        return super().preArchiveMove()

    def preArchive(self):
        # Always, not just for betas. This is what actually brands the
        # product: it renames the bundle and binaries, installs the theme
        # the client reads at startup, and replaces the icons -- after the
        # build and before packaging, which is why it can rename things
        # the build itself could not.
        theme = self.sourceDir() / FILES365_THEME_FILE
        if not theme.exists():
            CraftCore.log.error(f"{theme} is missing -- refusing to package an unbranded client")
            return False
        if not utils.system(["python3", self.sourceDir() / "admin/theme_patcher.py", self.archiveDir(), theme]):
            return False
        return super().preArchive()
