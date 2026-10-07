# 서드파티 소프트웨어와 출처

meltPDF는 아래 소프트웨어를 사용합니다. 각 라이선스와 출처를 밝힙니다.

## RAR 지원

| 이름 | 쓰는 방식 | 라이선스 | 출처 |
|---|---|---|---|
| **UnRAR 7.00** (`tools/UnRAR.exe`) | RAR/CBR의 압축을 푸는 프로그램. 실행 파일에 포함해서 배포 | UnRAR 라이선스 (RAR 해제 용도로 다른 프로그램에 포함해 무료 배포 가능, RAR 압축 생성기 제작 금지) - 전문은 `tools/UnRAR_license.txt` | Alexander Roshal / RARLAB, https://www.rarlab.com/ . 빌드 정보와 수정 내역: `tools/README.md` |
| **rarfile** | RAR 파일의 목차(이름·크기·암호 여부)를 파이썬으로 읽기 | ISC | Marko Kreen, https://github.com/markokr/rarfile |

### 검토했지만 쓰지 않은 것 (참고)

| 이름 | 쓰지 않은 이유 |
|---|---|
| https://github.com/DanielCaz/python-unrar (MIT) | 라이브러리가 아니라 작은 GUI 프로그램. 내부에서 `patool`을 불러 외부 압축 도구에 다시 맡기는 구조라 도구 문제를 해결해 주지 않음 |
| https://pypi.org/project/unrar/ (GPL-3) | UnRAR 라이브러리(`unrar.dll`)를 ctypes로 부르는 얇은 껍데기. DLL을 포함해 주지 않고 2019년 이후 갱신이 없으며, GPL-3 라이선스라 같이 배포하면 이 프로젝트에도 GPL이 번질 수 있음 |
| https://kb.aspose.com/zip/python/extract-rar-files-using-python/ (Aspose.ZIP) | 상용 라이브러리(체험판 제한/유료 라이선스). 무료 프로젝트에 넣기에 부적절 |

## 그 밖의 라이브러리 (requirements.txt)

Pillow (HPND), img2pdf (LGPL-3.0), pikepdf (MPL-2.0), PyMuPDF (AGPL-3.0 / 상용), tkinterdnd2 (MIT), rarfile (ISC), PyInstaller (GPL-2.0 + 예외; 만든 exe 배포에는 제약 없음).
참고: PyMuPDF는 AGPL이라, 이 프로그램의 소스를 공개하지 않고 exe만 다른 사람에게 배포할 때는 라이선스 검토가 필요합니다. 개인적으로 쓰는 경우에는 해당 없음.
