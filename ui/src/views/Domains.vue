<!--
  Copyright (C) 2026 Dan Brown
  SPDX-License-Identifier: GPL-3.0-or-later
-->
<template>
  <div>
    <cv-grid fullWidth>
      <cv-row>
        <cv-column class="page-title">
          <h2>{{ $t("domains.title") }}</h2>
        </cv-column>
      </cv-row>
      <cv-row v-if="error.load">
        <cv-column>
          <NsInlineNotification
            kind="error"
            :title="$t('domains.cannot_load')"
            :description="error.load"
            :showCloseButton="false"
          />
        </cv-column>
      </cv-row>
      <cv-row v-if="notice.text">
        <cv-column>
          <NsInlineNotification
            :kind="notice.kind"
            :title="notice.title"
            :description="notice.text"
            @close="notice.text = ''"
          />
        </cv-column>
      </cv-row>
      <cv-row v-if="!loading.load && !dnshelperPresent">
        <cv-column>
          <NsInlineNotification
            kind="info"
            :title="$t('domains.dnshelper_absent_title')"
            :description="$t('domains.dnshelper_absent_description')"
            :showCloseButton="false"
            class="mg-bottom-md"
          />
        </cv-column>
      </cv-row>
      <cv-row>
        <cv-column>
          <p class="section-intro">{{ $t("domains.intro") }}</p>
        </cv-column>
      </cv-row>
      <cv-row>
        <cv-column>
          <NsDataTable
            :allRows="rows"
            :columns="columns"
            :rawColumns="['domain']"
            :sortable="true"
            :pageSizes="[10, 25, 50]"
            :overflow-menu="true"
            :isLoading="loading.load"
            :skeletonRows="3"
            :itemsPerPageLabel="core.$t('pagination.items_per_page')"
            :rangeOfTotalItemsLabel="core.$t('pagination.range_of_total_items')"
            :ofTotalPagesLabel="core.$t('pagination.of_total_pages')"
            :backwardText="core.$t('pagination.previous_page')"
            :forwardText="core.$t('pagination.next_page')"
            :pageNumberLabel="core.$t('pagination.page_number')"
            @updatePage="page = $event"
          >
            <template slot="empty-state">
              <NsEmptyState :title="$t('domains.no_domains')">
                <template #description>
                  <div>{{ $t("domains.no_domains_description") }}</div>
                </template>
              </NsEmptyState>
            </template>
            <template slot="data">
              <cv-data-table-row
                v-for="(row, i) in page"
                :key="row.domain"
                :value="String(i)"
              >
                <cv-data-table-cell>
                  <strong>{{ row.domain }}</strong>
                  <cv-tag
                    v-if="row.orphaned"
                    :label="$t('domains.orphaned')"
                    kind="warm-gray"
                    class="mg-left-sm"
                  />
                </cv-data-table-cell>
                <cv-data-table-cell>
                  <NsToggle
                    :value="'enabled-' + row.domain"
                    :checked="row.enabled"
                    @change="toggleDomain(row)"
                    :disabled="
                      loading.toggle === row.domain || (row.orphaned && !row.enabled)
                    "
                    hideLabel
                    :label="$t('domains.enabled')"
                  />
                </cv-data-table-cell>
                <cv-data-table-cell>
                  <cv-tag
                    :label="$t('domains.dns_status_' + row.dnsSummary)"
                    :kind="dnsTagKind(row.dnsSummary)"
                  />
                </cv-data-table-cell>
                <cv-data-table-cell>
                  <cv-tag
                    :label="
                      $t(
                        row.enabled
                          ? 'domains.route_status_' + row.route_status
                          : 'domains.route_status_not_applicable'
                      )
                    "
                    :kind="row.enabled && row.route_status === 'configured' ? 'green' : 'gray'"
                  />
                </cv-data-table-cell>
                <cv-data-table-cell class="table-overflow-menu-cell">
                  <cv-overflow-menu flip-menu class="table-overflow-menu">
                    <cv-overflow-menu-item @click="showDnsStatus(row)">
                      <NsMenuItem
                        :icon="Certificate20"
                        :label="$t('domains.dns_status')"
                      />
                    </cv-overflow-menu-item>
                    <cv-overflow-menu-item
                      :disabled="!row.enabled"
                      @click="showProfileLink(row)"
                    >
                      <NsMenuItem
                        :icon="Link20"
                        :label="$t('domains.get_profile_link')"
                      />
                    </cv-overflow-menu-item>
                  </cv-overflow-menu>
                </cv-data-table-cell>
              </cv-data-table-row>
            </template>
          </NsDataTable>
        </cv-column>
      </cv-row>
    </cv-grid>

    <DnsStatusModal
      :isShown="isDnsStatusShown"
      :domain="current ? current.domain : ''"
      :dnshelperPresent="dnshelperPresent"
      @hide="isDnsStatusShown = false"
      @changed="load"
    />
    <ProfileLinkModal
      :isShown="isProfileLinkShown"
      :domain="current ? current.domain : ''"
      @hide="isProfileLinkShown = false"
    />
  </div>
</template>

<script>
import { mapState } from "vuex";
import {
  QueryParamService,
  IconService,
  UtilService,
  PageTitleService,
} from "@nethserver/ns8-ui-lib";
import AutomxService from "../mixins/automx";
import DnsStatusModal from "../components/DnsStatusModal.vue";
import ProfileLinkModal from "../components/ProfileLinkModal.vue";

export default {
  name: "Domains",
  components: { DnsStatusModal, ProfileLinkModal },
  mixins: [
    AutomxService,
    QueryParamService,
    IconService,
    UtilService,
    PageTitleService,
  ],
  pageTitle() {
    return this.$t("domains.title") + " - " + this.appName;
  },
  data() {
    return {
      q: { page: "domains" },
      urlCheckInterval: null,
      domains: [],
      dnshelperPresent: false,
      page: [],
      current: null,
      isDnsStatusShown: false,
      isProfileLinkShown: false,
      notice: { kind: "success", title: "", text: "" },
      loading: { load: false, toggle: "" },
      error: { load: "" },
    };
  },
  computed: {
    ...mapState(["core", "appName"]),
    columns() {
      return [
        "domain",
        "enabled",
        "dns_status",
        "route_status",
      ].map((c) => this.$t("domains.col_" + c));
    },
    rows() {
      return this.domains.map((d) => ({
        ...d,
        dnsSummary: this.summarizeDns(d.dns.records),
      }));
    },
  },
  beforeRouteEnter(to, from, next) {
    next((vm) => {
      vm.watchQueryData(vm);
      vm.urlCheckInterval = vm.initUrlBindingForApp(vm, vm.q.page);
    });
  },
  beforeRouteLeave(to, from, next) {
    clearInterval(this.urlCheckInterval);
    next();
  },
  created() {
    this.load();
  },
  methods: {
    async load() {
      this.loading.load = true;
      this.error.load = "";
      try {
        const out = await this.callAction("get-domains");
        this.domains = out.domains;
        this.dnshelperPresent = out.dnshelper_present;
      } catch (err) {
        this.error.load = this.errorText(err);
      }
      this.loading.load = false;
    },
    summarizeDns(records) {
      // Worst-status-wins rollup for the table's summary tag; the modal
      // shows the full per-record breakdown.
      const priority = [
        "not_permitted",
        "conflict",
        "unknown",
        "missing",
        "unmanaged",
        "ok",
      ];
      for (const status of priority) {
        if (records.some((r) => r.status === status)) {
          return status;
        }
      }
      return "unknown";
    },
    dnsTagKind(status) {
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
    say(kind, title, text) {
      this.notice = { kind, title, text };
    },
    async toggleDomain(row) {
      this.loading.toggle = row.domain;
      try {
        const out = await this.callAction("set-domains", {
          data: { domains: { [row.domain]: { enabled: !row.enabled } } },
        });
        if (out.route_failures.includes(row.domain)) {
          this.say(
            "warning",
            this.$t("domains.waiting_for_dns_title"),
            this.$t("domains.waiting_for_dns_description", {
              domain: row.domain,
            })
          );
        }
        await this.load();
      } catch (err) {
        this.say(
          "error",
          this.$t("action.set-domains"),
          this.errorText(err)
        );
      }
      this.loading.toggle = "";
    },
    showDnsStatus(row) {
      this.current = row;
      this.isDnsStatusShown = true;
    },
    showProfileLink(row) {
      this.current = row;
      this.isProfileLinkShown = true;
    },
  },
};
</script>

<style scoped lang="scss">
@import "../styles/carbon-utils";

.section-intro {
  margin-bottom: $spacing-05;
  max-width: 50rem;
}
</style>
