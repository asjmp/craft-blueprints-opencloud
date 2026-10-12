import info


class subinfo(info.infoclass):
    def setTargets(self):
        for ver in ["main"]:
            # This fork, not upstream. The package below sets
            # dailyUpdate = True, so pointing this at opencloud-eu would
            # have Craft pull upstream's blueprints over ours on the next
            # build and silently un-brand the client -- the build would
            # succeed and ship as OpenCloud. See DO-598.
            self.svnTargets[ver] = f"[git]https://github.com/asjmp/craft-blueprints-opencloud.git|{ver}|"
        self.defaultTarget = "main"

    def setDependencies(self):
        self.buildDependencies["craft/craft-core"] = "default"


from Package.SourceOnlyPackageBase import *


class Package(SourceOnlyPackageBase):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.subinfo.options.package.disableBinaryCache = True
        self.subinfo.options.dailyUpdate = True

    def unpack(self):
        return True

    def install(self):
        return True

    def qmerge(self):
        if not SourceOnlyPackageBase.qmerge(self):
            return False
        CraftCore.cache.clear()
        return True

    def createPackage(self):
        return True

    def checkoutDir(self, index=0):
        return CraftCore.standardDirs.blueprintRoot() / self.package.name
