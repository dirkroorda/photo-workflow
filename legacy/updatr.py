import re
import os
import sys
import urllib
import yaml
from subprocess import run
from importlib import import_module

import webbrowser
import pprint

pp = pprint.PrettyPrinter(indent=2)


COMMANDS = dict(
    meta2flat="read metadata from disk, apply it to the photos in the flat directory",
    flat2meta="read metadata from photos in flat directory, write to local directory",
    ph2flat="export compilation from Photos to flat directory in _local",
    ph2organized="export compilation from Photos to organized directory in _local",
    ph2dropbox="export compilation from Photos to organized directory on Dropbox",
    flat2flickr="sync additions/deletions, metadata, albums with Flickr",
    update="sync changed photos to flickr and dropbox",
    put="put all photos to flickr and dropbox",
)
COMMAND_STR = "\n".join(f"{k:<10} : {v}" for (k, v) in sorted(COMMANDS.items()))


HELP = f"""
updatr «source» «work» «command»

source: a directory where the characteristics of works are described
work:   the name of a yaml file in source/yaml that describes a work

command:
{COMMAND_STR}

-h
--help
help  : print help and exit
"""


REPO_DIR = f"{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}"
FLICKR_CONFIG = f"{REPO_DIR}/_local/flickr.yaml"

TOML_DIR = f"{REPO_DIR}/toml"
TOML_FILES = ("flat", "organized", "dropbox")

DROPBOX_DIR = os.path.expanduser("~/Dropbox")
DROPBOX_DIR = os.path.expanduser("~/DropboxTest")


IPTC = (
    ("source", "Iptc.Application2.Source", None),
    ("credit", "Iptc.Application2.Credit", None),
    ("copyright", "Iptc.Application2.Copyright", "Exif.Image.Copyright"),
    ("author", "Iptc.Application2.Byline", "Exif.Image.Artist"),
    ("writer", "Iptc.Application2.Writer", None),
    ("caption", "Iptc.Application2.Caption", "Exif.Image.ImageDescription"),
)

IPTC_FROM_LOGICAL = {entry[0]: entry[1] for entry in IPTC}
EXIF_FROM_LOGICAL = {entry[0]: entry[2] for entry in IPTC}

CAPTION_SEP = "\n---\n"
COLOFON_RE = re.compile(
    r"""(?:(?:\s*\(Bron:\s*)|(?:{})).*$""".format(CAPTION_SEP), re.S
)


def require(moduleName):
    module = import_module(moduleName)
    globals()[moduleName] = module
    return module


def console(*args, error=False):
    device = sys.stderr if error else sys.stdout
    device.write(" ".join(args) + "\n")
    device.flush()


def pretty(data):
    print(pp.pprint(data))


def readArgs():
    class A:
        pass

    A.source = None
    A.work = None
    A.command = None

    args = sys.argv[1:]

    if not len(args):
        console(HELP)
        console("Missing source and work and command")
        return None

    if args[0] in {"-h", "--help", "help"}:
        console(HELP)
        return None

    source = args[0]
    A.source = source
    args = args[1:]

    if not len(args):
        console(HELP)
        console("Missing work and command")
        return None

    if args[0] in {"-h", "--help", "help"}:
        console(HELP)
        return None

    work = args[0]
    A.work = work
    args = args[1:]

    if not len(args):
        console(HELP)
        console("Missing command")
        return None

    if args[0] in {"-h", "--help", "help"}:
        console(HELP)
        return None

    command = args[0]
    A.command = command
    args = args[1:]
    A.args = args

    if command not in COMMANDS:
        console(HELP)
        console(f"Wrong command: «{' '.join(args)}»")
        return None

    return A


def readYaml(path):
    with open(path) as fh:
        settings = yaml.load(fh, Loader=yaml.FullLoader)
    return settings


class Make:
    def __init__(self, source, work):
        class C:
            pass

        self.C = C
        self.source = source
        self.work = work
        self.good = True

        if not self.config():
            self.good = False

    def config(self):
        C = self.C
        source = self.source
        source = os.path.abspath(source)
        work = self.work

        c = dict(source=source, work=work)

        inDir = f"{source}/{work}"
        compConfig = f"{inDir}/config.yaml"

        if not os.path.exists(compConfig):
            console(f"No yaml file found for {work}: {compConfig}")
            return None

        with open(compConfig) as fh:
            settings = yaml.load(fh, Loader=yaml.FullLoader)
            for (k, v) in settings.items():
                if k == "skipKeywords":
                    c["skipTags"] = "|".join(f"/{s},|{s}/," for s in v)
                    v = set(v)
                elif k == "photoLib":
                    v = os.path.expanduser(v)
                c[k] = v

        c["dropboxPath"] = f"{DROPBOX_DIR}/{c['dropboxDir']}"

        localDir = f"{source}/_local/{work}"
        c["localDir"] = localDir
        c["flatDir"] = f"{localDir}/Flat"
        c["organizedDir"] = f"{localDir}/Organized"
        c["albumDir"] = f"{localDir}/albums"
        c["tomlOutDir"] = f"{localDir}/toml"
        reportDir = f"{localDir}/csv"
        c["reportDir"] = reportDir
        c["reportFlat"] = f"{reportDir}/flat.csv"
        c["reportOrganized"] = f"{reportDir}/organized.csv"
        c["reportDropbox"] = f"{reportDir}/dropbox.csv"
        tomlDir = f"{localDir}/toml"
        c["tomlDir"] = tomlDir
        c["tomlFlat"] = f"{tomlDir}/flat.toml"
        c["tomlOrganized"] = f"{tomlDir}/organized.toml"
        c["tomlDropbox"] = f"{tomlDir}/dropbox.toml"

        c["metaInDir"] = f"{inDir}/metadata"
        c["metaOutDir"] = f"{localDir}/metadata"

        if not os.path.exists(FLICKR_CONFIG):
            console(f"No flickr config file found: {FLICKR_CONFIG}")
            return None
        with open(FLICKR_CONFIG) as fh:
            for (k, v) in yaml.load(fh, Loader=yaml.FullLoader).items():
                c[k] = v

        for (k, v) in c.items():
            setattr(C, k, v)

        for wd in (
            C.flatDir,
            C.organizedDir,
            C.metaOutDir,
            C.tomlOutDir,
            C.reportDir,
            C.dropboxPath,
        ):
            if not os.path.exists(wd):
                os.makedirs(wd, exist_ok=True)

        tomlInPath = f"{TOML_DIR}/export.toml"
        if not os.path.exists(tomlInPath):
            console(f"File not found: {tomlInPath}")
            return None

        with open(tomlInPath) as fh:
            tInLines = list(fh)

        for tomlFile in TOML_FILES:
            tomlOutPath = f"{localDir}/toml/{tomlFile}.toml"
            tOutLines = []

            for line in tInLines:
                for k in (
                    "albumName",
                    "authors",
                    "report",
                    "skipTags",
                ):
                    useK = f"{k}{tomlFile[0].upper()}{tomlFile[1:]}" if k == "report" else k
                    val = getattr(C, useK, None)
                    if val is not None:
                        line = line.replace(f"«{k}»", val)
                if tomlFile == "flat" and line.startswith("directory"):
                    continue
                tOutLines.append(line)

            with open(tomlOutPath, "w") as fh:
                fh.write("".join(tOutLines))

        return True

    def doCommand(self, command):
        getattr(self, command)()

    def meta2flat(self):
        C = self.C
        defaults = C.iptcDefaults
        pyexiv2 = require("pyexiv2")

        with os.scandir(C.flatDir) as it:
            for entry in it:
                fName = entry.name
                if (
                    fName.startswith(".")
                    or not fName.endswith(".jpg")
                    or not entry.is_file()
                ):
                    continue
                inPath = f"{C.metaInDir}/{fName.removesuffix('jpg')}yaml"
                outPath = f"{C.flatDir}/{fName}"

                if os.path.exists(inPath):
                    with open(inPath) as fh:
                        logical = yaml.load(fh, Loader=yaml.FullLoader)
                else:
                    logical = {}

                info = pyexiv2.ImageMetadata(outPath)
                info.read()

                actual = {}
                for (log, iName, eName) in IPTC:
                    val = logical.get(log, None)
                    if val is None:
                        val = defaults[log]
                    actual[log] = str(val)

                actual["sourceAsUrl"] = urllib.parse.quote_plus(actual["source"])
                cpr = actual["copyright"]
                caption = actual["caption"]

                actual["copyright"] = cpr.format(**actual)
                colofon = C.colofon.format(**actual)

                caption = COLOFON_RE.sub("", caption)
                actual["caption"] = f"{caption}{CAPTION_SEP}{colofon}"

                for (log, iName, eName) in IPTC:
                    val = actual[log]
                    if iName is not None:
                        info[iName] = [val]
                    if eName is not None:
                        info[eName] = val

                info.write()

    def flat2meta(self):
        C = self.C
        defaults = C.iptcDefaults

        pyexiv2 = require("pyexiv2")

        with os.scandir(C.flatDir) as it:
            for entry in it:
                fName = entry.name
                if (
                    fName.startswith(".")
                    or not fName.endswith(".jpg")
                    or not entry.is_file()
                ):
                    continue
                inPath = f"{C.flatDir}/{fName}"
                outPath = f"{C.metaOutDir}/{fName.removesuffix('jpg')}yaml"

                info = pyexiv2.ImageMetadata(inPath)
                info.read()
                iptc = {}
                eNames = set(info.exif_keys)
                iNames = set(info.iptc_keys)

                actual = {}

                for (log, iName, eName) in IPTC:
                    iVal = [""] if iName not in iNames else info[iName].value
                    iVal = "\n".join(iVal)
                    eVal = "" if eName not in eNames else info[eName].value
                    val = eVal if not iVal or eVal and len(eVal) > len(iVal) else iVal
                    if log == "caption":
                        val = COLOFON_RE.sub("", val)
                    actual[log] = val

                actual["sourceAsUrl"] = urllib.quote_plus(actual["source"])

                for (log, iName, eName) in IPTC:
                    val = actual[log]

                    default = defaults[log]
                    if log == "copyright":
                        default = defaults[log].format(**actual)

                    if val and val != default:
                        iptc[log] = val

                with open(outPath, "w") as exh:
                    yaml.dump(iptc, exh, allow_unicode=True)

    def ph2flat(self):
        C = self.C
        run(
            (
                f"osxphotos export"
                f" {C.photoLib} {C.flatDir}"
                f" --load-config {C.tomlFlat}"
            ),
            shell=True,
        )

    def ph2organized(self):
        C = self.C
        run(
            (
                f"osxphotos export"
                f" {C.photoLib} {C.organizedDir}"
                f" --load-config {C.tomlOrganized}"
            ),
            shell=True,
        )

    def ph2dropbox(self):
        C = self.C
        run(
            (
                f"osxphotos export"
                f" {C.photoLib} {C.dropboxPath}"
                f" --load-config {C.tomlDropbox}"
            ),
            shell=True,
        )

    def flat2flickr(self):
        if not getattr(self, "keywordList", None):
            self.phGetMeta()
        if not getattr(self, "albumFromId", None):
            self.flGetAlbums()
        self.phGetModified()
        self.flPutModified()
        self.flPutAlbums()

    def update(self):
        self.ph2flat()
        self.flat2flickr()
        self.ph2dropbox()

    def put(self):
        self.ph2flat()
        self.flat2flickr()
        self.ph2dropbox()

    def phGetMeta(self):
        C = self.C
        osxphotos = require("osxphotos")
        photosdb = osxphotos.PhotosDB(dbfile=C.photoLib)
        photos = photosdb.photos(albums=[C.albumName])
        keywordSet = set()
        keywordsFromName = {}
        descriptionsFromName = {}
        self.keywordsFromName = keywordsFromName
        self.descriptionsFromName = descriptionsFromName

        for photoInfo in photos:
            fName = photoInfo.original_filename.removesuffix(".jpg")
            description = photoInfo.description
            keywords = photoInfo.keywords
            useKeywords = []
            for keyword in keywords:
                if keyword not in C.skipKeywords:
                    keywordSet.add(keyword.lower())
                    useKeywords.append(keyword)
            useKeywords.append(C.albumName)
            keywordsFromName[fName] = set(useKeywords)
            descriptionsFromName[fName] = description

        self.keywordList = [C.albumName.lower()] + sorted(keywordSet)

    def phGetModified(self):
        C = self.C
        self.ph2flat()

        modifications = {}
        self.modifications = modifications
        nNew = 0
        nUpdated = 0
        nDeleted = 0
        total = 0

        with open(C.reportFlat) as fh:
            next(fh)
            for line in fh:
                fields = line.rstrip("\n").split(",")
                name = fields[0].rsplit("/", 1)[1]
                if not name.endswith(".jpg"):
                    continue
                name = name.removesuffix(".jpg")
                total += 1
                new = fields[2]
                updated = fields[3]
                exif_updated = fields[5]
                deleted = fields[17]

                if new == "1":
                    modifications[name] = "new"
                    nNew += 1
                if new == "0" and (updated == "1" or exif_updated == "1"):
                    modifications[name] = "updated"
                    nUpdated += 1
                if deleted == "1":
                    modifications[name] = "deleted"
                    nDeleted += 1

        print(
            f"""
    All photos: {total:>3}
    New:        {nNew:>3}
    Updated:    {nUpdated:>3}
    Deleted:    {nDeleted:>3}
    """
        )

    def flConnect(self):
        C = self.C
        if not getattr(self, "flickr", None):
            flickrapi = require("flickrapi")
            flickr = flickrapi.FlickrAPI(
                C.flickrKey, C.flickrSecret, format="parsed-json"
            )

            if not flickr.token_valid(perms="write"):
                flickr.get_request_token(oauth_callback="oob")
                authorize_url = flickr.auth_url(perms="write")
                webbrowser.open_new_tab(authorize_url)
                verifier = str(input("Verifier code: "))
                flickr.get_access_token(verifier)
            self.flickr = flickr

    def flGetPhotos(self, albumId):
        C = self.C
        flickr = self.flickr

        data = flickr.photosets.getPhotos(user_id=C.flickrUserId, photoset_id=albumId)[
            "photoset"
        ]
        nPages = data["pages"]
        albumPhotos = data["photo"]
        if nPages > 1:
            for p in range(2, nPages + 1):
                data = flickr.photosets.getPhotos(
                    user_id=C.flickrUserId, photoset_id=albumId, page=p
                )["photoset"]
                albumPhotos.extend(data["photo"])
        return albumPhotos

    def flGetAlbums(self):
        C = self.C

        if not getattr(self, "keywordList", None):
            self.phGetMeta()
        keywordSet = set(self.keywordList)

        self.flConnect()
        flickr = self.flickr

        allAlbums = flickr.photosets.getList(user_id=C.flickrUserId)["photosets"][
            "photoset"
        ]
        idFromAlbum = {}
        albumFromId = {}
        albumsFromPhoto = {}
        photoFromId = {}
        idFromPhoto = {}
        self.photoFromId = photoFromId
        self.idFromPhoto = idFromPhoto
        self.idFromAlbum = idFromAlbum
        self.albumFromId = albumFromId
        self.albumsFromPhoto = albumsFromPhoto

        for album in allAlbums:
            albumTitle = album["title"]["_content"]
            if albumTitle.lower() not in keywordSet:
                continue
            albumId = album["id"]
            idFromAlbum[albumTitle] = albumId
            albumFromId[albumId] = albumTitle

        for (albumId, albumTitle) in albumFromId.items():
            albumPhotos = self.flGetPhotos(albumId)
            print(f"{albumTitle} {len(albumPhotos):>4} photos")

            for photo in albumPhotos:
                photoId = photo["id"]
                fileName = photo["title"]
                photoFromId[photoId] = fileName
                idFromPhoto[fileName] = photoId
                albumsFromPhoto.setdefault(fileName, set()).add(albumTitle)

        print(f"Total: {len(albumFromId):>4} albums on Flickr")
        print(f"Total: {len(photoFromId):>4} photos on Flickr")
        print(f"Total: {len(idFromPhoto):>4} titles on Flickr")

    def flPutModified(self):
        modifications = self.modifications

        if not modifications:
            print("No metadata updates")
            return

        for (name, kind) in sorted(modifications.items()):
            if kind == "updated":
                self.flPutPhoto(name)
                print(f"REPLACED: {name}")

    def flPutPhoto(self, name):
        C = self.C
        flickr = self.flickr

        idFromPhoto = self.idFromPhoto
        descriptionsFromName = self.descriptionsFromName

        fileName = f"{C.flatDir}/{name}.jpg"
        photoId = idFromPhoto[name]
        with open(fileName, "rb") as fh:
            flickr.replace(fileName, photoId, fh, format="rest")
        description = descriptionsFromName[name]
        if description:
            flickr.photos.setMeta(photo_id=photoId, description=description)

    def flPutAlbums(self):
        flickr = self.flickr

        keywordsFromName = self.keywordsFromName
        albumsFromPhoto = self.albumsFromPhoto
        idFromPhoto = self.idFromPhoto
        idFromAlbum = self.idFromAlbum

        touchedAlbums = set()

        for (name, photoId) in idFromPhoto.items():
            keywords = keywordsFromName.get(name, set())
            albums = albumsFromPhoto.get(name, set())
            print(f"{name} {keywords=} {albums=}")
            for k in keywords:
                if k not in albums:
                    print(f"add {name} to album {k}")
                    albumId = idFromAlbum.get(k, None)
                    if albumId is None:
                        print(f"\tmake new album {k}")
                        albumId = self.flMakeAlbum(k, photoId)
                    else:
                        flickr.photosets.addPhoto(photoset_id=albumId, photo_id=photoId)
                    touchedAlbums.add(albumId)
            for a in albums:
                if a not in keywords:
                    print(f"remove {name} from album {k}")
                    albumId = idFromAlbum[a]
                    flickr.photosets.removePhoto(photoset_id=albumId, photo_id=photoId)

        for albumId in sorted(touchedAlbums):
            photos = flickr.photosets
            photos = ",".join(photo["id"] for photo in self.flGetPhotos(albumId))
            flickr.photosets.reorderPhotos(photoset_id=albumId, photo_ids=photos)

    def flMakeAlbum(self, name, photoId):
        flickr = self.flickr
        albumFromId = self.albumFromId
        idFromAlbum = self.idFromAlbum

        result = flickr.photosets.create(title=name, primary_photo_id=photoId)
        albumId = result["photoset"]["id"]
        albumFromId[albumId] = name
        idFromAlbum[name] = albumId
        return albumId


def main():
    A = readArgs()
    if A is None:
        return 0

    source = A.source
    work = A.work
    command = A.command

    if not work:
        return

    Mk = Make(source, work)

    return Mk.doCommand(command)


if __name__ == "__main__":
    sys.exit(main())
