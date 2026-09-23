<!--
  Copyright (C) 2026 Dan Brown
  SPDX-License-Identifier: GPL-3.0-or-later
-->
<template>
  <NsModal
    size="large"
    :visible="isShown"
    :isLoading="loading.load"
    @modal-hidden="hide"
    @primary-click="load"
  >
    <template slot="title">{{
      $t("dns_status.title", { domain: domain })
    }}</template>
    <template slot="content">
      <NsInlineNotification
        v-if="error.load"
        kind="error"
        :title="$t('action.check-dns')"
        :description="error.load"
        :showCloseButton="false"
        class="mg-bottom-md"
      />
      <template v-else>
        <NsInlineNotification
          v-if="dns && dns.managed && dns.allowed === false"
          kind="warning"
          :title="$t('dns_status.not_permitted_title')"
          :showCloseButton="false"
          class="mg-bottom-md"
        >
          <template #description>
            <p>
              {{
                $t("dns_status.not_permitted_description", { zone: dns.zone })
              }}
            </p>
            <p class="mg-top-sm">{{ $t("dns_status.suggested_rule") }}</p>
            <NsCodeSnippet
              :copyTooltip="core.$t('common.copy_to_clipboard')"
              :copy-feedback="core.$t('common.copied_to_clipboard')"
              :wrap-text="true"
              hideExpandButton
              class="mg-top-sm"
              >{{ suggestedRuleText }}</NsCodeSnippet
            >
          </template>
        </NsInlineNotification>
        <NsInlineNotification
          v-else-if="dns && !dns.managed"
          kind="info"
          :title="$t('dns_status.manual_title')"
          :description="$t('dns_status.manual_description')"
          :showCloseButton="false"
          class="mg-bottom-md"
        />

        <cv-structured-list v-if="dns">
          <template slot="headings">
            <cv-structured-list-heading>{{
              $t("dns_status.col_record")
            }}</cv-structured-list-heading>
            <cv-structured-list-heading>{{
              $t("dns_status.col_type")
            }}</cv-structured-list-heading>
            <cv-structured-list-heading>{{
              $t("dns_status.col_value")
            }}</cv-structured-list-heading>
            <cv-structured-list-heading>{{
              $t("dns_status.col_status")
            }}</cv-structured-list-heading>
          </template>
          <template slot="items">
            <cv-structured-list-item
              v-for="record in dns.records"
              :key="record.host + record.type"
            >
              <cv-structured-list-data class="break-word">{{
                record.host
              }}</cv-structured-list-data>
              <cv-structured-list-data
                ><cv-tag :label="record.type" kind="blue"
              /></cv-structured-list-data>
              <cv-structured-list-data class="break-word">{{
                record.value
              }}</cv-structured-list-data>
              <cv-structured-list-data>
                <cv-tag
                  :label="$t('domains.dns_status_' + record.status)"
                  :kind="statusKind(record.status)"
                />
              </cv-structured-list-data>
            </cv-structured-list-item>
          </template>
        </cv-structured-list>

        <!-- create/overwrite, dnshelper path only -->
        <template v-if="dns && dns.managed && dns.allowed">
          <div class="mg-top-md" v-if="preview">
            <p class="mg-bottom-sm">
              <strong>{{ $t("dns_status.preview_title") }}</strong>
            </p>
            <p
              v-if="
                !preview.changes.add.length && !preview.changes.remove.length
              "
            >
              {{ $t("dns_status.preview_nothing") }}
            </p>
            <ul v-else class="preview-list">
              <li v-for="(r, i) in preview.changes.add" :key="'add' + i">
                + {{ r.name }} {{ r.type }} {{ r.data }}
              </li>
              <li v-for="(r, i) in preview.changes.remove" :key="'remove' + i">
                - {{ r.name }} {{ r.type }} {{ r.data }}
              </li>
            </ul>
            <NsInlineNotification
              v-if="error.apply"
              kind="error"
              :title="$t('action.apply-dns')"
              :description="error.apply"
              :showCloseButton="false"
              class="mg-top-sm"
            />
            <NsButton
              kind="primary"
              :loading="loading.apply"
              :disabled="loading.apply"
              @click="confirm"
              class="mg-right-sm mg-top-sm"
            >
              {{ $t("dns_status.confirm") }}
            </NsButton>
            <NsButton
              kind="secondary"
              :disabled="loading.apply"
              @click="preview = null"
            >
              {{ core.$t("common.cancel") }}
            </NsButton>
          </div>
          <div class="mg-top-md" v-else>
            <NsButton
              v-if="hasMissing"
              kind="tertiary"
              :loading="loading.dryRun === 'create'"
              :disabled="!!loading.dryRun"
              @click="dryRun('create')"
              class="mg-right-sm"
            >
              {{ $t("dns_status.create") }}
            </NsButton>
            <NsButton
              v-if="hasConflict"
              kind="tertiary"
              :loading="loading.dryRun === 'overwrite'"
              :disabled="!!loading.dryRun"
              @click="dryRun('overwrite')"
            >
              {{ $t("dns_status.overwrite") }}
            </NsButton>
          </div>
        </template>

        <!-- manual path: exact records to create -->
        <template v-if="dns && !canApply">
          <p class="mg-top-md mg-bottom-sm">
            <strong>{{ $t("dns_status.records_to_create") }}</strong>
          </p>
          <NsCodeSnippet
            :copyTooltip="core.$t('common.copy_to_clipboard')"
            :copy-feedback="core.$t('common.copied_to_clipboard')"
            :wrap-text="true"
            hideExpandButton
            >{{ planText }}</NsCodeSnippet
          >
        </template>
      </template>
    </template>
    <template slot="secondary-button">{{ core.$t("common.close") }}</template>
    <template slot="primary-button">{{
      $t("dns_status.check_again")
    }}</template>
  </NsModal>
</template>

<script>
import { mapState } from "vuex";
import { IconService, UtilService } from "@nethserver/ns8-ui-lib";
import AutomxService from "../mixins/automx";

export default {
  name: "DnsStatusModal",
  mixins: [AutomxService, IconService, UtilService],
  props: {
    isShown: { type: Boolean, default: false },
    domain: { type: String, default: "" },
    dnshelperPresent: { type: Boolean, default: false },
  },
  data() {
    return {
      dns: null,
      plan: [],
      preview: null,
      pendingAction: "",
      loading: { load: false, apply: false, dryRun: "" },
      error: { load: "", apply: "" },
    };
  },
  computed: {
    ...mapState(["core"]),
    hasMissing() {
      return this.dns.records.some((r) => r.status === "missing");
    },
    hasConflict() {
      return this.dns.records.some((r) => r.status === "conflict");
    },
    canApply() {
      return this.dns && this.dns.managed && this.dns.allowed;
    },
    suggestedRuleText() {
      return (
        `module/${this.$store.state.instanceName}  zone: ${
          this.dns ? this.dns.zone : ""
        }  ` +
        "names: autoconfig, autoconfig.*, autodiscover, autodiscover.*, " +
        "_autodiscover._tcp, _autodiscover._tcp.*  types: CNAME, SRV"
      );
    },
    planText() {
      return this.plan
        .map((r) => `${r.host}\t${r.suggested_ttl}\tIN\t${r.type}\t${r.value}`)
        .join("\n");
    },
  },
  watch: {
    isShown(shown) {
      if (shown) {
        this.preview = null;
        this.load();
      }
    },
  },
  methods: {
    hide() {
      this.$emit("hide");
    },
    async load() {
      this.loading.load = true;
      this.error.load = "";
      try {
        const out = await this.callAction("check-dns", {
          data: { domain: this.domain },
        });
        this.dns = out.results[0].dns;
        if (!this.canApply) {
          const plan = await this.callAction("get-dns-plan", {
            data: { domain: this.domain },
          });
          this.plan = plan.records;
        }
      } catch (err) {
        this.error.load = this.errorText(err);
      }
      this.loading.load = false;
    },
    statusKind(status) {
      return (
        {
          ok: "green",
          missing: "gray",
          conflict: "red",
          not_permitted: "magenta",
          unmanaged: "gray",
          unknown: "gray",
        }[status] || "gray"
      );
    },
    async dryRun(action) {
      this.loading.dryRun = action;
      this.error.apply = "";
      try {
        this.preview = await this.callAction("apply-dns", {
          data: { domain: this.domain, action, dry_run: true },
        });
        this.pendingAction = action;
      } catch (err) {
        this.error.apply = this.errorText(err);
      }
      this.loading.dryRun = "";
    },
    async confirm() {
      this.loading.apply = true;
      this.error.apply = "";
      try {
        await this.callAction("apply-dns", {
          data: {
            domain: this.domain,
            action: this.pendingAction,
            dry_run: false,
          },
        });
        this.preview = null;
        await this.load();
        this.$emit("changed");
      } catch (err) {
        this.error.apply = this.errorText(err);
      }
      this.loading.apply = false;
    },
  },
};
</script>

<style scoped lang="scss">
@import "../styles/carbon-utils";

.break-word {
  word-wrap: break-word;
  max-width: 20vw;
}

.preview-list {
  font-family: monospace;
  font-size: 0.85rem;
  list-style: none;
  padding-left: 0;
}
</style>
