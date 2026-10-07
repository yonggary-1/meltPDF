# tools/ - 같이 들어 있는 외부 도구

## UnRAR.exe (RAR/CBR 압축 풀기용)

| 항목 | 내용 |
|---|---|
| 정체 | **UnRAR 7.00** 윈도우용 명령줄 프로그램 (64비트, 정적 링크 - 별도 DLL 설치 불필요) |
| 원작자 / 공식 사이트 | Alexander Roshal, RARLAB - https://www.rarlab.com/ (UnRAR 소스: https://www.rarlab.com/rar_add.htm) |
| 만든 소스 | 공식 UnRAR 7.00 소스. 이 빌드는 Ubuntu 패키지 `unrar-nonfree` 1:7.0.7-1build1의 원본 소스 묶음(`unrar-nonfree_7.0.7.orig.tar.gz`, SHA-256 `da95829c7e66fe461c06eb4bea8145e58d88d76909432d0875cd1ff86669f728`, 공식 소스 그대로)에서 받았습니다. |
| 라이선스 | UnRAR 라이선스(`UnRAR_license.txt`, 아래에 전문 포함). 요약: RAR를 푸는 용도로 어떤 소프트웨어에든 무료로 넣어 배포할 수 있고, RAR **압축을 만드는** 프로그램을 만드는 데는 쓸 수 없습니다. |
| 소스 수정 | 단 한 줄: `isnt.cpp`의 `bstr_t("...")` 두 곳을 `_bstr_t(L"...")`로 바꿨습니다. MSVC 전용 라이브러리 없이 mingw로 컴파일하기 위한 것이며 RAR 해제 동작과는 무관합니다(`unrar-mingw.patch`). |
| 만든 방법 | 리눅스에서 mingw-w64(`x86_64-w64-mingw32-g++`)로 교차 컴파일 (`build_unrar_windows.sh`) |
| SHA-256 | `b6f5befc3dfcccb1026bde363a7bf7a2b3ce01055c9942a923db460c5799b6aa` |

### 확인한 것 / 확인하지 못한 것
- 확인: Wine(윈도우 API 호환 계층) 위에서 이 `UnRAR.exe`로 RAR 5 일반/연속(solid) 압축 파일을 풀어 원본과 바이트가 같은 것을 확인했고, 암호 파일은 오류 코드 11로 거절하는 것을 확인했습니다. 외부 DLL 의존은 윈도우 기본 DLL(KERNEL32, ADVAPI32, SHELL32, OLE32 등)뿐입니다.
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
