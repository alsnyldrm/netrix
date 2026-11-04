"""Transient API dictionaries backed by typed relationships, never JSON columns."""

from sqlalchemy import inspect
from sqlalchemy.orm.attributes import flag_dirty


def changed(row):
    if inspect(row).persistent:
        flag_dirty(row)


class Payload:
    @property
    def data(self):
        if "_pending_data" in self.__dict__:
            return self.__dict__["_pending_data"]
        from .records import observation_data

        return observation_data(self)

    @data.setter
    def data(self, value):
        self.__dict__["_pending_data"] = dict(value or {})
        changed(self)


class NetworkPayload:
    @property
    def evidence(self):
        if "_pending_evidence" in self.__dict__:
            return self.__dict__["_pending_evidence"]
        from .network import read

        return read(self)

    @evidence.setter
    def evidence(self, value):
        self.__dict__["_pending_evidence"] = dict(value or {})
        changed(self)


class DiscoveryPayload:
    @property
    def evidence(self):
        if "_pending_evidence" in self.__dict__:
            return self.__dict__["_pending_evidence"]
        if self.failed:
            return {"failed": True, "error_class": self.error_class}
        return self.network_state.evidence if self.network_state else {}

    @evidence.setter
    def evidence(self, value):
        self.__dict__["_pending_evidence"] = dict(value or {})
        changed(self)


class ResultPayload:
    @property
    def values(self):
        if "_pending_values" in self.__dict__:
            return self.__dict__["_pending_values"]
        from .resolutions import read

        return read(self)

    @values.setter
    def values(self, value):
        self.__dict__["_pending_values"] = dict(value or {})
        changed(self)

    @property
    def address_scope(self):
        return [self.scope_address, self.scope_vrf, self.scope_vlan]

    @address_scope.setter
    def address_scope(self, value):
        self.scope_address, self.scope_vrf, self.scope_vlan = value

    @property
    def issues(self):
        return [
            dict(source=r.source, code=r.code, message=r.message)
            for r in sorted(self.issue_rows, key=lambda r: r.position)
        ]

    @issues.setter
    def issues(self, value):
        from .models import ResolutionIssue

        self.issue_rows = [
            ResolutionIssue(position=i, **{k: r.get(k, "") for k in ("source", "code", "message")})
            for i, r in enumerate(value or [])
        ]

    @property
    def steps(self):
        result = []
        for r in sorted(self.step_rows, key=lambda r: r.position):
            d = dict(source=r.source, status=r.status)
            if r.at:
                d["at"] = r.at.isoformat()
            if r.label:
                d["device"] = r.label
            if r.mode:
                d["mode"] = r.mode
            result.append(d)
        return result

    @steps.setter
    def steps(self, value):
        from datetime import datetime

        from .models import ResolutionStep

        self.step_rows = [
            ResolutionStep(
                position=i,
                source=r["source"],
                status=r["status"],
                at=datetime.fromisoformat(r["at"]) if r.get("at") else None,
                label=r.get("device", ""),
                mode=r.get("mode", ""),
            )
            for i, r in enumerate(value or [])
        ]
