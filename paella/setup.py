
import os
import sys
import tempfile
import textwrap
from .platform import OnPlatform, Platform
from .error import *

#----------------------------------------------------------------------------------------------

class Runner:
    def __init__(self, nop=False):
        self.nop = nop
        # self.has_sudo = sh('command -v sudo') != ''
        self.has_sudo = False

    def run(self, cmd, at=None, output_on_error=False, _try=False, sudo=False):
        if cmd.find('\n') > -1:
            cmds1 = str.lstrip(textwrap.dedent(cmd))
            cmds = filter(lambda s: str.lstrip(s) != '', cmds1.split("\n"))
            cmd = "; ".join(cmds)
        if self.has_sudo and sudo:
            cmd = "sudo " + cmd
        print(cmd)
        sys.stdout.flush()
        if self.nop:
            return
        if output_on_error:
            fd, temppath = tempfile.mkstemp()
            os.close(fd)
            cmd = "{{ {}; }} >{} 2>&1".format(cmd, temppath)
        if at is None:
            rc = os.system(cmd)
        else:
            with cwd(at):
                rc = os.system(cmd)
        if rc > 0:
            if output_on_error:
                os.system("cat {}".format(temppath))
                os.remove(temppath)
            eprint("command failed: " + cmd)
            sys.stderr.flush()
            if not _try:
                sys.exit(1)
        return rc

    @staticmethod
    def has_command(cmd):
        return os.system("command -v " + cmd + " > /dev/null") == 0

#----------------------------------------------------------------------------------------------

class RepoRefresh(OnPlatform):
    def __init__(self, runner):
        OnPlatform.__init__(self)
        self.runner = runner

    def redhat_compat(self):
        pass

    def debian_compat(self):
        self.runner.run("apt-get -qq update -y", sudo=True)

    def macos(self):
        if os.environ.get('BREW_NO_UPDATE') != '1':
            self.runner.run("brew update || true")

#----------------------------------------------------------------------------------------------

class Setup(OnPlatform):
    def __init__(self, nop=False):
        OnPlatform.__init__(self)
        self.runner = Runner(nop)
        self.stages = [0]
        self.platform = Platform()
        self.os = self.platform.os
        self.arch = self.platform.arch
        self.osnick = self.platform.osnick
        self.dist = self.platform.dist
        self.ver = self.platform.os_ver
        self.repo_refresh = True

        self.python = sys.executable

        if self.os == 'macos':
            if 'VIRTUAL_ENV' not in os.environ:
                # required because osx pip installed are done with --user
                os.environ["PATH"] = os.environ["PATH"] + ':' + os.environ["HOME"] + '/Library/Python/2.7/bin'
            # this prevents brew updating before each install
            os.environ["HOMEBREW_NO_AUTO_UPDATE"] = "1"

        if self.platform.is_debian_compat():
            # prevents apt-get from interactively prompting
            os.environ["DEBIAN_FRONTEND"] = 'noninteractive'

        os.environ["PYTHONWARNINGS"] = 'ignore:DEPRECATION::pip._internal.cli.base_command'

    def setup(self):
        if self.repo_refresh:
            RepoRefresh(self.runner).invoke()
        self.invoke()

    def run(self, cmd, at=None, output_on_error=False, _try=False, sudo=False):
        return self.runner.run(cmd, at=at, output_on_error=output_on_error, _try=_try, sudo=sudo)

    @staticmethod
    def has_command(cmd):
        return Runner.has_command(cmd)

    #------------------------------------------------------------------------------------------

    def apt_install(self, packs, group=False, _try=False):
        self.run("apt-get -qq install -y " + packs, output_on_error=True, _try=_try, sudo=True)

    def yum_install(self, packs, group=False, _try=False):
        if not group:
            self.run("yum install -q -y " + packs, output_on_error=True, _try=_try, sudo=True)
        else:
            self.run("yum groupinstall -y " + packs, output_on_error=True, _try=_try, sudo=True)

    def dnf_install(self, packs, group=False, _try=False):
        if not group:
            self.run("dnf install -y " + packs, output_on_error=True, _try=_try, sudo=True)
        else:
            self.run("dnf groupinstall -y " + packs, output_on_error=True, _try=_try, sudo=True)

    def zypper_install(self, packs, group=False, _try=False):
        self.run("zipper --non-interactive install " + packs, output_on_error=True, _try=_try, sudo=True)

    def pacman_install(self, packs, group=False, _try=False):
        self.run("pacman --noconfirm -S " + packs, output_on_error=True, _try=_try, sudo=True)

    def brew_install(self, packs, group=False, _try=False):
        # brew will fail if package is already installed
        for pack in packs.split():
            self.run("brew list {} &>/dev/null || brew install {}".format(pack, pack), output_on_error=True, _try=_try)

    def pkg_install(self, packs, group=False, _try=False):
        self.run("pkg install -q -y " + packs, output_on_error=True, _try=_try, sudo=True)

    def install(self, packs, group=False, _try=False):
        if self.os == 'linux':
            if self.dist == 'fedora': # also include centos 8
                self.dnf_install(packs, group=group, _try=_try)
            elif self.platform.is_debian_compat():
                self.apt_install(packs, group=group, _try=_try)
            elif self.platform.is_redhat_compat():
                self.yum_install(packs, group=group, _try=_try)
            elif self.dist == 'suse':
                self.zypper_install(packs, group=group, _try=_try)
            elif self.dist == 'arch':
                self.pacman_install(packs, group=group, _try=_try)
            else:
                raise self.Error("Cannot determine installer")
        elif self.os == 'macos':
            self.brew_install(packs, group=group, _try=_try)
        elif self.os == 'freebsd':
            self.pkg_install(packs, group=group, _try=_try)
        else:
            raise Error("Cannot determine installer")

    def group_install(self, packs, _try=False):
        self.install(packs, group=True, _try=_try)

    #------------------------------------------------------------------------------------------

    def yum_add_repo(self, repourl, repo="", _try=False):
        if not self.has_command("yum-config-manager"):
            self.install("yum-utils")
        self.run("yum-config-manager -y --add-repo {}".format(repourl), _try=_try, sudo=True)

    def apt_add_repo(self, repourl, repo="", _try=False):
        if not self.has_command("add-apt-repository"):
            self.install("software-properties-common")
        self.run("add-apt-repository -y {}".format(repourl), _try=_try, sudo=True)
        self.run("apt-get -qq update", _try=_try, sudo=True)

    def dnf_add_repo(self, repourl, repo="", _try=False):
        if self.run("dnf config-manager 2>/dev/null", _try=True):
            self.install("dnf-plugins-core", _try=_try)
        self.run("dnf config-manager -y --add-repo {}".format(repourl), _try=_try, sudo=True)

    def zypper_add_repo(self, repourl, repo="", _try=False):
        pass

    def pacman_add_repo(self, repourl, repo="", _try=False):
        pass

    def brew_add_repo(self, repourl, repo="", _try=False):
        pass

    def add_repo(self, repourl, repo="", _try=False):
        if self.os == 'linux':
            if self.dist == 'fedora':
                self.dnf_add_repo(repourl, repo=repo, _try=_try)
            elif self.dist == 'ubuntu' or self.dist == 'debian':
                self.apt_add_repo(repourl, repo=repo, _try=_try)
            elif self.dist == 'centos' or self.dist == 'redhat':
                self.yum_add_repo(repourl, repo=repo, _try=_try)
            elif self.dist == 'suse':
                self.zypper_add_repo(repourl, repo=repo, _try=_try)
            elif self.dist == 'arch':
                self.pacman_add_repo(repourl, repo=repo, _try=_try)
            else:
                raise Error("Cannot determine installer")
        elif self.os == 'macos':
            self.brew_add_repo(packs, group=group, _try=_try)
        else:
            raise Error("Cannot determine installer")

    #------------------------------------------------------------------------------------------

    def pip_install(self, cmd, _try=False):
        pip_user = ''
        if self.os == 'macos' and 'VIRTUAL_ENV' not in os.environ:
            pip_user = '--user '
        self.run(self.python + " -m pip install --disable-pip-version-check " + pip_user + cmd,
                 output_on_error=True, _try=_try, sudo=True)

    def pip3_install(self, cmd, _try=False):
        self.pip_install(cmd, _try=_try)

    def setup_pip(self, _try=False):
        if self.run(self.python + " -m pip --version", _try=True, output_on_error=False) != 0:
            if sys.version_info.major == 3:
                # required for python >= 3.6, may not exist in prior versions
                self.install("python3-distutils", _try=True)
            self.install_downloaders()
            with_sudo = self.os != 'macos'
            pip_user = ' --user' if self.os == 'macos' else ''
            self.run("wget -q https://bootstrap.pypa.io/get-pip.py -O /tmp/get-pip.py",
                     output_on_error=True, _try=_try)
            self.run(self.python + " /tmp/get-pip.py pip==19.3.1" + pip_user,
                     output_on_error=True, _try=_try, sudo=with_sudo)
            if sys.version_info.major == 3:
                self.pip_install("setuptools==49.3.0")

    #------------------------------------------------------------------------------------------

    def install_downloaders(self, _try=False):
        if self.os == 'linux':
            self.install("ca-certificates", _try=_try)
        self.install("curl wget", _try=_try)

    def install_git_lfs_on_linux(self, _try=False):
        if self.arch == 'x64':
            lfs_arch = 'amd64'
        elif self.arch == 'arm64v8':
            lfs_arch = 'arm64'
        elif self.arch == 'arm32v7':
            lfs_arch = 'arm'
        else:
            raise Error("Cannot determine platform for git-lfs installation")
        self.run("""
            set -e
            d=$(mktemp -d /tmp/git-lfs.XXXXXX)
            mkdir -p $d
            wget -q https://github.com/git-lfs/git-lfs/releases/download/v2.12.1/git-lfs-linux-{}-v2.12.1.tar.gz -O $d/git-lfs.tar.gz
            (cd $d; tar xf git-lfs.tar.gz)
            $d/install.sh
            rm -rf $d
            """.format(lfs_arch))

    def install_gnu_utils(self, _try=False):
        packs = ""
        if self.os == 'macos':
            packs= "make coreutils findutils gnu-sed gnu-tar gawk"
        elif self.os == 'freebsd':
            packs = "gmake coreutils findutils gsed gtar gawk"
        self.install(packs)
        for x in ['make', 'find', 'sed', 'tar', 'mktemp']:
            p = "/usr/local/bin/{}".format(x)
            if not os.path.exists(p):
                self.run("ln -sf /usr/local/bin/g{} {}".format(x, p))
            else:
                eprint("Warning: {} exists - not replaced".format(p))

    def install_linux_gnu_tar(self, _try=False):
        if self.os != 'linux':
            eprint("Warning: not Linux - tar not installed")
            return
        if self.arch != 'x64':
            raise Error("Cannot install gnu tar on non-x64 platform")
        self.run("""
            dir=$(mktemp -d /tmp/tar.XXXXXX)
            (cd $dir; wget -q -O tar.tgz http://redismodules.s3.amazonaws.com/gnu/gnu-tar-1.32-x64-centos7.tgz; tar -xzf tar.tgz -C /; )
            rm -rf $dir
            """)

    def install_ubuntu_modern_gcc(self, _try=False):
        if self.dist != 'ubuntu':
            eprint("Warning: not Ubuntu - modern gcc not installed")
            return
        self.install("software-properties-common")
        self.run("add-apt-repository -y ppa:ubuntu-toolchain-r/test")
        self.run("apt-get -qq update")
        self.install("gcc-7 g++-7")
        self.run("update-alternatives --install /usr/bin/gcc gcc /usr/bin/gcc-7 60 --slave /usr/bin/g++ g++ /usr/bin/g++-7")
        self.run("update-alternatives --config gcc")
