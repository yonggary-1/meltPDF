#!/bin/bash
# tools/UnRAR.exe를 다시 만드는 방법(리눅스에서 mingw-w64로 윈도우용 교차 컴파일). 자세한 설명은 tools/README.md.
#   준비:  sudo apt-get install g++-mingw-w64-x86-64-posix
#   원본:  UnRAR 소스(rarlab.com의 unrarsrc, 또는 Ubuntu/Debian 패키지 unrar-nonfree 7.0.7의 orig.tar.gz)를 풀어 둔 폴더에서 실행
#   사용:  cd <unrar 소스 폴더> && bash build_unrar_windows.sh
set -e
CXX=x86_64-w64-mingw32-g++-posix
SHIM=$(mktemp -d)
# mingw의 헤더 이름은 소문자라서(윈도우에서는 대소문자 무시) 대문자 이름으로 부르는 두 헤더를 연결해 준다
echo '#include <powrprof.h>' > "$SHIM/PowrProf.h"
echo '#include <wbemidl.h>'  > "$SHIM/Wbemidl.h"
# -DUNICODE -D_UNICODE -DCUSTOM_CMDLINE_PARSER: 명령줄을 윈도우 시스템 문자 코드(한국어 윈도우는 cp949)가 아니라 유니코드 그대로 받는다.
#   없으면 일본어/중국어 등 cp949에 없는 글자가 든 압축 파일 경로의 그 글자가 '?'로 바뀐다. (공식 UnRAR의 Visual Studio 프로젝트도 이 설정을 쓴다)
# isnt.cpp의 문자열->BSTR 변환(MSVC 전용 라이브러리 필요)을 와이드 문자열 생성자로 바꾼다 (tools/unrar-mingw.patch)
patch -p0 isnt.cpp < "$(dirname "$0")/unrar-mingw.patch" || true
OBJS="rar strlist strfn pathfn smallfn global file filefn filcreat archive arcread unicode system crypt crc rawread encname resource match timefn rdwrfn consio options errhnd rarvm secpassword rijndael getbits sha1 sha256 blake2s hash extinfo extract volume list find unpack headers threadpool rs16 cmddata ui filestr recvol rs scantree qopen isnt"
mkdir -p out
for o in $OBJS; do $CXX -O2 -std=c++11 -w -I"$SHIM" -DUNRAR -DRAR_SMP -DUNICODE -D_UNICODE -DCUSTOM_CMDLINE_PARSER -c $o.cpp -o out/$o.o; done
$CXX -O2 -o out/UnRAR.exe out/*.o -static -static-libgcc -static-libstdc++ -pthread \
     -lshlwapi -lole32 -loleaut32 -luuid -lpowrprof -ladvapi32 -luser32 -lshell32 -lwbemuuid
x86_64-w64-mingw32-strip out/UnRAR.exe
echo "만들어진 파일: out/UnRAR.exe"
