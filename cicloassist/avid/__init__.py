# ⛔ Antes de qualquer `avb.open`: sem isto, regravar uma bin com string nula a condena
#    inteira no Media Composer (`FILE_OPEN_FAILURE`). Ver `avb_fiel.py`.
from cicloassist.avid import avb_fiel as _avb_fiel  # noqa: F401
