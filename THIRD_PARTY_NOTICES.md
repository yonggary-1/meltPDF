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

라이선스는 설치된 패키지의 메타데이터와 동봉된 라이선스 파일에서 확인한 값입니다(확인한 버전을 함께 적음).

| 이름 | 확인한 버전 | 라이선스 | 비고 |
|---|---|---|---|
| **PyMuPDF** | 1.28.2 | **AGPL-3.0 또는 Artifex 상용 라이선스 (이중)** | 이 프로젝트의 라이선스를 AGPL로 정하게 된 이유. 패키지의 `COPYING` 파일은 이 이중 라이선스를 한 줄로 알릴 뿐 전문이 아님 |
| img2pdf | 0.6.3 | LGPL-3.0 | 무손실 JPEG 삽입 |
| pikepdf | 10.16.0 | MPL-2.0 | 휠에 포함된 qpdf 등 부품의 라이선스는 패키지의 `licenses/third-party-licenses` 폴더에 있음. MPL-2.0은 AGPL로의 결합을 허용(2차 라이선스) |
| Pillow | 12.3.0 | MIT-CMU (HPND 계열) | |
| tkinterdnd2 | 0.6.3 | MIT | |
| rarfile | 4.5 | ISC | 위 RAR 지원 참고 |
| PyInstaller (exe 만들 때만 사용) | 6.22.3 | GPL-2.0 이상 + 부트로더 예외 | 부트로더 예외로 만들어진 exe는 어떤 라이선스로든 배포 가능. 공식 `COPYING.txt`에서 확인 |

### 이 프로젝트의 라이선스를 정한 과정

- 배포하는 exe에는 PyMuPDF가 들어갑니다. PyMuPDF를 오픈소스 쪽 조건으로 쓰려면 AGPL-3.0이 적용되므로, 이 프로젝트를 **AGPL-3.0 이상(AGPL-3.0-or-later)** 으로 정했습니다.
- img2pdf(LGPL-3.0), pikepdf(MPL-2.0), Pillow, tkinterdnd2, rarfile은 AGPL-3.0 프로젝트에 함께 넣어 배포할 수 있는 조건입니다. (LGPL-3.0은 GPL-3.0의 추가 허용이며 GPL-3.0 §13이 AGPL과의 결합을 허용, MPL-2.0은 "2차 라이선스"로 AGPL을 명시)
- UnRAR(`tools/UnRAR.exe`)는 별도로 실행되는 프로그램이며 UnRAR 라이선스(RAR 해제 용도의 재배포 허용, 압축 생성기 제작 금지)를 따릅니다. AGPL이 적용되는 대상이 아닙니다.
- exe를 다른 사람에게 배포할 때는 소스 저장소 위치를 함께 알려야 합니다(AGPL). 개인적으로 쓰기만 할 때는 해당 없음.
- PyMuPDF를 쓰지 않거나 Artifex 상용 라이선스를 사면 다른 라이선스를 고를 수 있습니다.
- 법률 자문이 아니라 각 라이선스 조건을 읽고 정리한 것입니다. 배포 범위가 넓어지면 전문가 검토를 권합니다.
- **`LICENSE` 파일**은 공식 원문(GNU AGPL v3)이어야 합니다. 이 작업 환경에서는 원문 사이트(gnu.org)에 접속할 수 없어 받지 못했고 임의로 작성하지 않았습니다. GitHub 저장소 화면의 "Add file → Create new file → 파일 이름에 `LICENSE` 입력 → Choose a license template → GNU Affero General Public License v3.0"로 추가하세요.
