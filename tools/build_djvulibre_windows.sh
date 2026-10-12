#!/bin/sh
# DjVuLibre의 ddjvu.exe / djvused.exe(윈도우 64비트, 정적 링크)를 리눅스에서 mingw-w64로 교차 컴파일한다.
# 쓴 소스: 같은 폴더의 djvulibre/ 안에 있는 Ubuntu 24.04 소스 패키지(공식 3.5.28 소스 + 보안 패치들).
# 필요한 것: mingw-w64, autoconf, automake, libtool, pkg-config, dpkg-dev(dpkg-source)
#   sudo apt-get install mingw-w64 autoconf automake libtool pkg-config dpkg-dev
# 사용: sh tools/build_djvulibre_windows.sh   -> tools/ddjvu.exe, tools/djvused.exe 를 새로 만든다
set -e
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
cd "$WORK"
cp "$HERE"/djvulibre/djvulibre_3.5.28* .
dpkg-source -x djvulibre_3.5.28-2ubuntu0.24.04.2.dsc src        # 원본 소스를 풀고 debian/patches 의 패치를 적용
cd src
autoreconf -fi
# DJVUAPI 등을 비워 두는 이유: 이 매크로가 윈도우에서 기본으로 dllimport가 되어, 정적 라이브러리와 링크할 수 없다.
./configure --host=x86_64-w64-mingw32 --enable-static --disable-shared --disable-xmltools --disable-desktopfiles \
    --without-jpeg --without-tiff \
    CPPFLAGS="-DDJVUAPI= -DDDJVUAPI= -DMINILISPAPI=" \
    LDFLAGS="-static -static-libgcc -static-libstdc++"
make -j"$(nproc)"
x86_64-w64-mingw32-strip -o "$HERE/ddjvu.exe" tools/ddjvu.exe
x86_64-w64-mingw32-strip -o "$HERE/djvused.exe" tools/djvused.exe
sha256sum "$HERE/ddjvu.exe" "$HERE/djvused.exe"
rm -rf "$WORK"
