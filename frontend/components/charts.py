"""Chart rendering helpers using matplotlib for simple, explainable visuals."""

from __future__ import annotations

import matplotlib.pyplot as plt
import pandas as pd
import streamlit as st

from frontend.utils.formatters import pct


def plot_category_accuracy(category_df: pd.DataFrame) -> None:
    if category_df.empty:
        st.info("No category data for this run.")
        return

    ordered = category_df.sort_values("accuracy", ascending=False)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(ordered["category"], ordered["accuracy"], color="#35608D")
    ax.set_ylim(0.0, 1.0)
    ax.set_ylabel("Accuracy")
    ax.set_title("Accuracy by Category")
    ax.tick_params(axis="x", rotation=30)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    st.pyplot(fig, use_container_width=True)


def plot_error_type_frequency(error_df: pd.DataFrame) -> None:
    if error_df.empty:
        st.info("No error types recorded.")
        return

    ordered = error_df.sort_values("count", ascending=False)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(ordered["error_type"], ordered["count"], color="#A64040")
    ax.set_ylabel("Count")
    ax.set_title("Error Type Frequency")
    ax.tick_params(axis="x", rotation=30)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    st.pyplot(fig, use_container_width=True)


def plot_pass_fail_distribution(pass_fail_df: pd.DataFrame) -> None:
    if pass_fail_df.empty:
        st.info("No pass/fail distribution available.")
        return

    fig, ax = plt.subplots(figsize=(5, 4))
    ax.bar(pass_fail_df["status"], pass_fail_df["count"], color=["#2F855A", "#B23B3B"])
    ax.set_ylabel("Count")
    ax.set_title("Pass / Fail Distribution")
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    st.pyplot(fig, use_container_width=True)


def plot_oracle_pass_rate(oracle_df: pd.DataFrame) -> None:
    if oracle_df.empty:
        st.info("No oracle pass-rate data available.")
        return

    ordered = oracle_df.sort_values("pass_rate", ascending=False)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(ordered["oracle_type"], ordered["pass_rate"], color="#4C7F72")
    ax.set_ylim(0.0, 1.0)
    ax.set_ylabel("Pass Rate")
    ax.set_title("Pass Rate by Oracle Type")
    ax.tick_params(axis="x", rotation=30)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    st.pyplot(fig, use_container_width=True)


def plot_oracle_usage(oracle_df: pd.DataFrame) -> None:
    if oracle_df.empty:
        st.info("No oracle usage data available.")
        return

    ordered = oracle_df.sort_values("usage_count", ascending=False)
    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(ordered["oracle_type"], ordered["usage_count"], color="#6E7FA8")
    ax.set_ylabel("Cases")
    ax.set_title("Oracle Usage Counts")
    ax.tick_params(axis="x", rotation=30)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    st.pyplot(fig, use_container_width=True)


def plot_category_accuracy_delta(delta_df: pd.DataFrame) -> None:
    if delta_df.empty:
        st.info("No category comparison data available.")
        return

    ordered = delta_df.sort_values("delta", ascending=False)
    colors = ["#2F855A" if value >= 0 else "#B23B3B" for value in ordered["delta"]]

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.bar(ordered["category"], ordered["delta"], color=colors)
    ax.axhline(0.0, color="black", linewidth=1)
    ax.set_ylabel("Accuracy Delta")
    ax.set_title("Category Accuracy Difference (Candidate - Baseline)")
    ax.tick_params(axis="x", rotation=30)
    ax.grid(axis="y", linestyle="--", alpha=0.3)
    st.pyplot(fig, use_container_width=True)


def show_rate_table(oracle_df: pd.DataFrame) -> None:
    if oracle_df.empty:
        return

    display_df = oracle_df.copy()
    display_df["pass_rate"] = display_df["pass_rate"].apply(pct)
    st.dataframe(display_df, use_container_width=True, hide_index=True)
