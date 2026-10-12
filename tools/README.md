# tools/ - 같이 들어 있는 외부 도구

## UnRAR.exe (RAR/CBR 압축 풀기용)

| 항목 | 내용 |
|---|---|
| 정체 | **UnRAR 7.00** 윈도우용 명령줄 프로그램 (64비트, 정적 링크 - 별도 DLL 설치 불필요) |
| 원작자 / 공식 사이트 | Alexander Roshal, RARLAB - https://www.rarlab.com/ (UnRAR 소스: https://www.rarlab.com/rar_add.htm) |
| 만든 소스 | 공식 UnRAR 7.00 소스. 이 빌드는 Ubuntu 패키지 `unrar-nonfree` 1:7.0.7-1build1의 원본 소스 묶음(`unrar-nonfree_7.0.7.orig.tar.gz`, SHA-256 `da95829c7e66fe461c06eb4bea8145e58d88d76909432d0875cd1ff86669f728`, 공식 소스 그대로)에서 받았습니다. |
| 라이선스 | UnRAR 라이선스(`UnRAR_license.txt`, 아래에 전문 포함). 요약: RAR를 푸는 용도로 어떤 소프트웨어에든 무료로 넣어 배포할 수 있고, RAR **압축을 만드는** 프로그램을 만드는 데는 쓸 수 없습니다. |
| 소스 수정 | 소스 코드는 한 줄만 바꿨습니다: `isnt.cpp`의 `bstr_t("...")` 두 곳을 `_bstr_t(L"...")`로 바꿨습니다. MSVC 전용 라이브러리 없이 mingw로 컴파일하기 위한 것이며 RAR 해제 동작과는 무관합니다(`unrar-mingw.patch`). 그 밖에 컴파일 옵션으로 `-DUNICODE -D_UNICODE -DCUSTOM_CMDLINE_PARSER`를 켰습니다(소스에 이미 있는 기능을 켜는 것이며, 공식 윈도우 빌드와 같은 설정입니다). 이것을 켜야 명령줄의 파일 경로가 시스템 문자 코드를 거치지 않고 유니코드 그대로 전달되어, 일본어/중국어 등 한국어 윈도우의 문자 코드(cp949)에 없는 글자가 든 경로도 올바르게 읽힙니다. |
| 만든 방법 | 리눅스에서 mingw-w64(`x86_64-w64-mingw32-g++`)로 교차 컴파일 (`build_unrar_windows.sh`) |
| SHA-256 | `729be76d39edd4d908da4ab085250179abe532f8774d0a5f40c99065cb844191` |

### 확인한 것 / 확인하지 못한 것
- 확인: Wine(윈도우 API 호환 계층) 위에서 이 `UnRAR.exe`로 RAR 5 일반/연속(solid) 압축 파일을 풀어 원본과 바이트가 같은 것을 확인했고, 암호 파일은 오류 코드 11로 거절하는 것을 확인했습니다. 외부 DLL 의존은 윈도우 기본 DLL(KERNEL32, ADVAPI32, SHELL32, OLE32 등)뿐입니다.
- 확인(유니코드 경로): Wine에서 `日本語_头像.rar`(cp949에 없는 글자 포함)를 명령줄(CreateProcessW, 파이썬이 쓰는 방식과 같음)로 넘겨 올바른 압축 파일 하나만 풀리는 것을 확인했습니다. 이전 빌드는 글자가 `?`로 바뀌어 `?`가 와일드카드로 해석되는 바람에, 같은 폴더의 이름 길이가 같은 다른 rar까지 같이 풀어 버렸습니다. 공백이 든 경로와 끝에 `\`가 붙은 대상 폴더, 암호 파일(코드 11)도 다시 확인했습니다.
- 확인하지 못함: 진짜 Windows에서의 실행. 의심스러우면 공식 사이트의 UnRAR로 이 파일을 바꿔 넣으면 됩니다(같은 이름으로 덮어쓰기).

### UnRAR 라이선스 전문 (UnRAR_license.txt)

 ******    *****   ******   UnRAR - free utility for RAR archives
 **   **  **   **  **   **  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 ******   *******  ******    License for use and distribution of
 **   **  **   **  **   **   ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
 **   **  **   **  **   **         FREE portable version
                                   ~~~~~~~~~~~~~~~~~~~~~

      The source code of UnRAR utility is freeware. This means:

   1. All copyrights to RAR and the utility UnRAR are exclusively
      owned by the author - Alexander Roshal.

   2. UnRAR source code may be used in any software to handle
      RAR archives without limitations free of charge, but cannot be
      used to develop RAR (WinRAR) compatible archiver and to
      re-create RAR compression algorithm, which is proprietary.
      Distribution of modified UnRAR source code in separate form
      or as a part of other software is permitted, provided that
      full text of this paragraph, starting from "UnRAR source code"
      words, is included in license, or in documentation if license
      is not available, and in source code comments of resulting package.

   3. The UnRAR utility may be freely distributed. It is allowed
      to distribute UnRAR inside of other software packages.

   4. THE RAR ARCHIVER AND THE UnRAR UTILITY ARE DISTRIBUTED "AS IS".
      NO WARRANTY OF ANY KIND IS EXPRESSED OR IMPLIED.  YOU USE AT 
      YOUR OWN RISK. THE AUTHOR WILL NOT BE LIABLE FOR DATA LOSS, 
      DAMAGES, LOSS OF PROFITS OR ANY OTHER KIND OF LOSS WHILE USING
      OR MISUSING THIS SOFTWARE.

   5. Installing and using the UnRAR utility signifies acceptance of
      these terms and conditions of the license.

   6. If you don't agree with terms of the license you must remove
      UnRAR files from your storage devices and cease to use the
      utility.

      Thank you for your interest in RAR and UnRAR.


                                            Alexander L. Roshal

## ddjvu.exe / djvused.exe (DjVu 쪽 풀기, 쪽 수와 서지 정보 읽기용, v0.16.0)

| 항목 | 내용 |
|---|---|
| 정체 | **DjVuLibre 3.5.28**의 명령줄 도구 두 개(윈도우 64비트, 정적 링크 - 별도 DLL 설치 불필요). `ddjvu`는 쪽을 그림(PNM)으로 풀고, `djvused`는 쪽 수와 서지 정보를 읽는다. |
| 원작자 / 공식 사이트 | Léon Bottou, Yann LeCun 외 (AT&T, LizardTech에서 시작) - https://djvu.sourceforge.net/ |
| 만든 소스 | Ubuntu 24.04 소스 패키지 `djvulibre 3.5.28-2ubuntu0.24.04.2` (공식 3.5.28 소스 + Fedora/Debian의 버그·보안 수정 패치 9개, 목록은 `djvulibre/` 안 debian 묶음의 `debian/patches/series`). 소스 묶음을 그대로 `tools/djvulibre/`에 넣어 두었다(GPL에 따라 실행 파일과 같이 소스를 제공). |
| 소스 SHA-256 | `djvulibre_3.5.28.orig.tar.xz` `1223b7bf7c8dfe2e290882f3bfb88ba2468b30495a1bf8dfd54dc7e810987887` / `djvulibre_3.5.28-2ubuntu0.24.04.2.debian.tar.xz` `b1b370a10f3d6542056f0c3a42201101ab095b878650fdf6c4fd31f44d4c851f` |
| 라이선스 | **GPL-2.0 이상**(GPL-2.0-or-later). 전문은 `djvulibre/COPYING`. 이 프로젝트(AGPL-3.0 이상)와 함께 배포할 수 있다(GPL-2.0 "이상"이라 GPL-3.0으로 쓸 수 있고, 따로 실행되는 프로그램이기도 함). |
| 소스 수정 | 없음. 컴파일 옵션만: 정적 라이브러리로 링크하려고 `DJVUAPI`, `DDJVUAPI`, `MINILISPAPI` 매크로를 비워 둠(윈도우에서 기본값이 DLL 가져오기라서). JPEG/TIFF 지원 없이 빌드(쪽 배경을 JPEG로 넣은 드문 djvu는 그 배경을 못 그릴 수 있음, TIFF 출력은 쓰지 않음). |
| 만든 방법 | 리눅스에서 mingw-w64로 교차 컴파일 (`build_djvulibre_windows.sh`, 같은 소스로 다시 만들 수 있음). 실행 파일 안의 빌드 시각만 달라 바이트가 매번 똑같지는 않다. |
| SHA-256 | `ddjvu.exe` `23f8788e0456216ead4d17baa72208675a084ccf843f9f0e7f388915c02cf589` / `djvused.exe` `991bbe65e116f437031e9d246edd641d54bef2477cd74f58f3c84a5165062c33` |

### 확인한 것 / 확인하지 못한 것
- 확인: Wine 위에서 이 두 exe로 시험용 djvu(흑백 3쪽 + 컬러 1쪽, 흑백 글자 + 컬러 배경 합성 쪽, 깨진 쪽이 있는 파일)를 풀어, 리눅스판 DjVuLibre와 출력이 바이트까지 같음을 확인했다(표준 출력은 이진 모드로 나옴). 한글 서지 정보(UTF-8), 쪽 수, 깨진 쪽에서의 오류 종료도 같았다. 외부 DLL 의존은 윈도우 기본 DLL(KERNEL32, ADVAPI32, msvcrt)뿐이다.
- 확인: 오류 메시지 번역 파일을 넣지 않아, 오류가 나면 영어 메시지 대신 메시지 이름이 나올 수 있다(meltPDF는 이를 짧게 줄여 보여 준다).
- 확인하지 못함: 진짜 Windows에서의 실행. 명령줄 경로는 시스템 문자 코드(cp949 등)로 받으므로, 그 문자 코드에 없는 글자(일본어 등)가 든 경로는 meltPDF가 파일을 임시 폴더에 영어 이름으로 복사해서 넘긴다.

