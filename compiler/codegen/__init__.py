"""Fase 6: Back-ends de geração de código (ARM64 nativo, x86 IA-32 didático e C portável)."""

from .arm64 import ARM64CodeGenerator
from .c_backend import CCodeGenerator
from .x86 import X86CodeGenerator

__all__ = ["ARM64CodeGenerator", "X86CodeGenerator", "CCodeGenerator"]
