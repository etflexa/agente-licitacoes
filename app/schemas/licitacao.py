"""Modelos das licitações — espelho do contrato exposto pela API do monitor.

Os nomes dos campos ficam em snake_case (idiomático em Python) e são
serializados em camelCase (`numeroProcesso`), que é o formato que a API do Node
usa. Assim o agente fala exatamente a mesma linguagem do restante do sistema.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic.alias_generators import to_camel

from app.utils.datas import para_datetime


class ModeloBase(BaseModel):
    """Base com conversão automática snake_case ↔ camelCase."""

    model_config = ConfigDict(
        alias_generator=to_camel,
        populate_by_name=True,
        extra="ignore",
    )


class Documento(ModeloBase):
    """Edital ou anexo publicado junto da licitação."""

    id: str | None = None
    nome: str | None = None
    tipo: str | None = None
    data_publicacao: datetime | None = None
    arquivo: str | None = None
    tamanho_bytes: int | None = None
    ativo: bool | None = None

    @field_validator("data_publicacao", mode="before")
    @classmethod
    def _converter_data(cls, valor: object) -> datetime | None:
        return para_datetime(valor)

    @property
    def tamanho_legivel(self) -> str | None:
        """Tamanho do arquivo em KB/MB, para exibição."""
        if not self.tamanho_bytes:
            return None
        megabytes = self.tamanho_bytes / (1024 * 1024)
        if megabytes >= 1:
            return f"{megabytes:.1f} MB"
        return f"{self.tamanho_bytes / 1024:.0f} KB"


class LicitacaoResumo(ModeloBase):
    """Versão enxuta usada em listagens e no contexto enviado ao LLM."""

    id: str
    modalidade: str | None = None
    numero_processo: str | None = None
    objeto: str | None = None
    data_abertura: datetime | None = None
    situacao: str | None = None
    criterio_de_julgamento: str | None = None
    link: str | None = None
    total_documentos: int = 0

    @field_validator("data_abertura", mode="before")
    @classmethod
    def _converter_data(cls, valor: object) -> datetime | None:
        return para_datetime(valor)


class Licitacao(LicitacaoResumo):
    """Registro completo, como devolvido por `GET /api/licitacoes/:id`."""

    modalidade_id: str | None = None
    data_situacao: datetime | None = None
    documentos: list[Documento] = Field(default_factory=list)
    legado: bool = False
    primeira_visualizacao_em: datetime | None = None
    atualizado_em: datetime | None = None

    @field_validator("data_situacao", mode="before")
    @classmethod
    def _converter_data_situacao(cls, valor: object) -> datetime | None:
        return para_datetime(valor)


class RespostaListaLicitacoes(ModeloBase):
    """Resposta paginada de `GET /api/licitacoes`."""

    total: int
    limit: int
    offset: int
    total_geral: int = 0
    itens: list[LicitacaoResumo] = Field(default_factory=list)


class StatusMonitor(ModeloBase):
    """Última execução do monitor, como reportada pelo Node."""

    sucesso: bool | None = None
    total_api: int | None = None
    novas: int | None = None
    alteradas: int | None = None
    duracao_segundos: float | None = None
    data_ultima_carga_api: datetime | None = None
    atualizado_em: datetime | None = None
    erro: str | None = None

    @field_validator("data_ultima_carga_api", "atualizado_em", mode="before")
    @classmethod
    def _converter_datas(cls, valor: object) -> datetime | None:
        return para_datetime(valor)


class ResumoLicitacoes(ModeloBase):
    """Agregados de `GET /api/licitacoes/resumo`."""

    total: int
    com_link: int = 0
    total_documentos: int = 0
    legado_sem_detalhes: int = 0
    por_modalidade: dict[str, int] = Field(default_factory=dict)
    por_situacao: dict[str, int] = Field(default_factory=dict)
    proxima_abertura: datetime | None = None
    status_monitor: StatusMonitor | None = None

    @field_validator("proxima_abertura", mode="before")
    @classmethod
    def _converter_data(cls, valor: object) -> datetime | None:
        return para_datetime(valor)


class ProximasAberturas(ModeloBase):
    """Resposta de `GET /api/licitacoes/proximas-aberturas`."""

    janela_dias: int
    de: datetime | None = None
    ate: datetime | None = None
    total: int
    itens: list[LicitacaoResumo] = Field(default_factory=list)

    @field_validator("de", "ate", mode="before")
    @classmethod
    def _converter_datas(cls, valor: object) -> datetime | None:
        return para_datetime(valor)


class FiltrosLicitacao(ModeloBase):
    """Filtros aceitos tanto pela API do agente quanto pela API do monitor.

    São convertidos em query string com os mesmos nomes que o Node entende,
    então a regra de filtragem continua existindo em um único lugar.
    """

    q: str | None = Field(
        default=None, description="Busca textual em processo, objeto, modalidade e situação"
    )
    modalidade: str | None = Field(default=None, description="Ex.: 'Pregão eletrônico'")
    situacao: str | None = Field(default=None, description="Ex.: 'Em processo' ou 'Finalizada'")
    de: date | None = Field(default=None, description="Data de abertura inicial (AAAA-MM-DD)")
    ate: date | None = Field(default=None, description="Data de abertura final (AAAA-MM-DD)")
    somente_com_link: bool = False
    somente_com_documentos: bool = False
    somente_futuras: bool = False
    ordenar: Literal["dataAbertura", "numeroProcesso", "modalidade", "situacao"] = "dataAbertura"
    direcao: Literal["asc", "desc"] = "asc"
    limit: int = Field(default=50, ge=1, le=500)
    offset: int = Field(default=0, ge=0)

    def para_query(self) -> dict[str, str]:
        """Converte em query string, omitindo valores vazios/falsos."""
        dados = self.model_dump(by_alias=True, exclude_none=True, mode="json")

        return {
            chave: str(valor).lower() if isinstance(valor, bool) else str(valor)
            for chave, valor in dados.items()
            if valor not in (None, "", False)
        }
