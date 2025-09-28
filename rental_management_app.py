import streamlit as st
import pandas as pd
from datetime import datetime, date
from dateutil.relativedelta import relativedelta
import uuid
import firebase_admin
from firebase_admin import credentials, firestore

# --- APP CONFIGURATION ---
st.set_page_config(
    page_title="Rental Property Management",
    page_icon="🏠",
    layout="wide"
)

# --- FIREBASE INTEGRATION ---
@st.cache_resource
def initialize_firebase():
    """Initializes Firebase connection using Streamlit secrets."""
    try:
        if not firebase_admin._apps:
            # Manually build the credentials dictionary from secrets
            creds_dict = {
                "type": st.secrets["firebase_credentials"]["type"],
                "project_id": st.secrets["firebase_credentials"]["project_id"],
                "private_key_id": st.secrets["firebase_credentials"]["private_key_id"],
                "private_key": st.secrets["firebase_credentials"]["private_key"],
                "client_email": st.secrets["firebase_credentials"]["client_email"],
                "client_id": st.secrets["firebase_credentials"]["client_id"],
                "auth_uri": st.secrets["firebase_credentials"]["auth_uri"],
                "token_uri": st.secrets["firebase_credentials"]["token_uri"],
                "auth_provider_x509_cert_url": st.secrets["firebase_credentials"]["auth_provider_x509_cert_url"],
                "client_x509_cert_url": st.secrets["firebase_credentials"]["client_x509_cert_url"],
            }
            cred = credentials.Certificate(creds_dict)
            firebase_admin.initialize_app(cred)
        return firestore.client()
    except Exception as e:
        st.error(f"Failed to initialize Firebase: {e}")
        st.warning("Please ensure your Firebase credentials are correctly set up in Streamlit secrets.")
        return None

db = initialize_firebase()

# --- HELPER FUNCTIONS ---
def load_data_from_firestore():
    """Loads all data from Firestore into st.session_state."""
    if db and 'data_loaded' not in st.session_state:
        with st.spinner("Loading data from database..."):
            st.session_state.tenants = []
            tenants_ref = db.collection('tenants').stream()
            for doc in tenants_ref:
                tenant_data = doc.to_dict()
                tenant_data['id'] = doc.id
                st.session_state.tenants.append(tenant_data)
            
            st.session_state.payments = []
            payments_ref = db.collection('payments').stream()
            for doc in payments_ref:
                payment_data = doc.to_dict()
                payment_data['id'] = doc.id
                st.session_state.payments.append(payment_data)

            st.session_state.expenses = []
            expenses_ref = db.collection('expenses').stream()
            for doc in expenses_ref:
                expense_data = doc.to_dict()
                expense_data['id'] = doc.id
                st.session_state.expenses.append(expense_data)
                
            st.session_state.data_loaded = True

def get_tenant_by_id(tenant_id):
    """Finds a tenant in session state by their ID."""
    for tenant in st.session_state.get('tenants', []):
        if tenant['id'] == tenant_id:
            return tenant
    return None

def calculate_balance(tenant_id, report_month):
    """Calculates the balance for a tenant for a given month."""
    tenant = get_tenant_by_id(tenant_id)
    if not tenant:
        return 0, 0, 0, 0, 0

    rent_due = tenant['rent']
    
    # Calculate balance from previous months
    previous_month = report_month - relativedelta(months=1)
    total_rent_charged_before = 0
    total_paid_before = 0
    
    start_date = datetime.strptime(tenant['start_date'], '%Y-%m-%d').date()
    current_month_iter = start_date
    while current_month_iter.strftime('%Y-%m') <= previous_month.strftime('%Y-%m'):
        total_rent_charged_before += tenant['rent']
        current_month_iter += relativedelta(months=1)

    for p in st.session_state.get('payments', []):
        payment_month = datetime.strptime(p['date'], '%Y-%m-%d').date().strftime('%Y-%m')
        if p['tenant_id'] == tenant_id and payment_month <= previous_month.strftime('%Y-%m'):
            total_paid_before += p['amount']
            
    balance_forwarded = total_rent_charged_before - total_paid_before
    
    paid_this_month = sum(p['amount'] for p in st.session_state.get('payments', [])
                          if p['tenant_id'] == tenant_id and 
                          datetime.strptime(p['date'], '%Y-%m-%d').date().strftime('%Y-%m') == report_month.strftime('%Y-%m'))
    
    total_due = rent_due + balance_forwarded
    new_balance = total_due - paid_this_month
    
    return rent_due, balance_forwarded, total_due, paid_this_month, new_balance


# --- UI SECTIONS ---
def show_dashboard():
    """Displays the main dashboard with KPIs and charts."""
    st.header("Financial Dashboard")

    # --- Date Range Filter ---
    today = datetime.now()
    start_of_year = date(today.year, 1, 1)
    
    date_range = st.date_input(
        "Select Date Range for Report",
        (start_of_year, today.date()),
        key='dashboard_date_range'
    )

    if len(date_range) != 2:
        st.warning("Please select a valid start and end date.")
        return

    start_date, end_date = date_range
    
    # Ensure data is loaded
    if 'tenants' not in st.session_state or 'payments' not in st.session_state or 'expenses' not in st.session_state:
        st.info("Data is loading or not yet available.")
        return

    # Filter data based on the selected date range
    payments_df = pd.DataFrame(st.session_state.payments)
    expenses_df = pd.DataFrame(st.session_state.expenses)

    # Convert date columns to datetime objects for comparison
    if not payments_df.empty:
        payments_df['date'] = pd.to_datetime(payments_df['date']).dt.date
        filtered_payments = payments_df[(payments_df['date'] >= start_date) & (payments_df['date'] <= end_date)]
    else:
        filtered_payments = pd.DataFrame(columns=['date', 'amount'])

    if not expenses_df.empty:
        expenses_df['date'] = pd.to_datetime(expenses_df['date']).dt.date
        filtered_expenses = expenses_df[(expenses_df['date'] >= start_date) & (expenses_df['date'] <= end_date)]
    else:
        filtered_expenses = pd.DataFrame(columns=['date', 'amount'])
    
    # --- KPIs ---
    total_income = filtered_payments['amount'].sum()
    total_expenses = filtered_expenses['amount'].sum()
    net_income = total_income - total_expenses
    
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Income", f"AED {total_income:,.2f}")
    col2.metric("Total Expenses", f"AED {total_expenses:,.2f}")
    col3.metric("Net Income", f"AED {net_income:,.2f}")

    st.markdown("---")

    # --- Monthly Net Income Chart ---
    st.subheader("Monthly Net Income")

    # Prepare data for chart
    if not filtered_payments.empty:
        filtered_payments['Month'] = pd.to_datetime(filtered_payments['date']).dt.to_period('M').astype(str)
        income_summary = filtered_payments.groupby('Month').agg(Income=('amount', 'sum')).reset_index()
    else:
        income_summary = pd.DataFrame(columns=['Month', 'Income'])

    if not filtered_expenses.empty:
        filtered_expenses['Month'] = pd.to_datetime(filtered_expenses['date']).dt.to_period('M').astype(str)
        expense_summary = filtered_expenses.groupby('Month').agg(Expenses=('amount', 'sum')).reset_index()
    else:
        expense_summary = pd.DataFrame(columns=['Month', 'Expenses'])

    # *** FIX: Use an outer merge and fill NaNs to prevent KeyError ***
    if not income_summary.empty or not expense_summary.empty:
        monthly_summary = pd.merge(income_summary, expense_summary, on='Month', how='outer')
        # Fill NaN values with 0 for months that have income but no expenses, or vice versa
        monthly_summary['Income'] = monthly_summary['Income'].fillna(0)
        monthly_summary['Expenses'] = monthly_summary['Expenses'].fillna(0)
        
        # Calculate Net Income
        monthly_summary['Net Income'] = monthly_summary['Income'] - monthly_summary['Expenses']
        
        # Sort by month to ensure the chart is chronological
        monthly_summary = monthly_summary.sort_values('Month')

        st.bar_chart(monthly_summary.set_index('Month')['Net Income'])
    else:
        st.info("No income or expense data available for the selected period to display a chart.")


def manage_tenants():
    st.title("👥 Tenant Management")
    
    with st.expander("➕ Add New Tenant", expanded=False):
        with st.form("new_tenant_form", clear_on_submit=True):
            name = st.text_input("Full Name")
            property_unit = st.text_input("Property/Unit")
            rent = st.number_input("Monthly Rent Amount", min_value=0.0, format="%.2f")
            deposit = st.number_input("Deposit Amount", min_value=0.0, format="%.2f")
            start_date = st.date_input("Lease Start Date", datetime.now().date())
            
            submitted = st.form_submit_button("Add Tenant")
            if submitted:
                if name and property_unit and rent > 0 and db:
                    with st.spinner("Adding new tenant..."):
                        new_tenant_data = {
                            'name': name, 'property': property_unit, 'rent': rent,
                            'start_date': start_date.strftime('%Y-%m-%d'),
                            'deposit': deposit
                        }
                        update_time, doc_ref = db.collection('tenants').add(new_tenant_data)
                        new_tenant_data['id'] = doc_ref.id
                        st.session_state.tenants.append(new_tenant_data)
                        st.success(f"Tenant '{name}' added successfully!")
                    st.rerun()
                else:
                    st.error("Please fill in all fields.")

    st.markdown("---")
    
    st.subheader("Current Tenants")
    if not st.session_state.get('tenants', []):
        st.info("No tenants found. Add a new tenant above.")
    else:
        search_query = st.text_input("Search Tenants by Name")
        
        filtered_tenants = [t for t in st.session_state.tenants if search_query.lower() in t['name'].lower()]

        if not filtered_tenants:
            st.warning("No tenants match your search.")
        else:
            for i, tenant in enumerate(filtered_tenants):
                with st.container():
                    st.markdown(f"#### {tenant['name']} ({tenant['property']})")
                    cols = st.columns([2, 2, 2, 1, 1])
                    cols[0].text(f"Monthly Rent: AED {tenant['rent']:,.2f}")
                    cols[1].text(f"Deposit: AED {tenant.get('deposit', 0.0):,.2f}")
                    cols[2].text(f"Start Date: {tenant['start_date']}")
                    
                    if cols[3].button("✏️ Edit", key=f"edit_{tenant['id']}"):
                        st.session_state.edit_tenant_id = tenant['id']

                    if cols[4].button("🗑️ Delete", key=f"delete_{tenant['id']}"):
                        if db:
                            with st.spinner("Deleting tenant..."):
                                db.collection('tenants').document(tenant['id']).delete()
                                # Also delete associated payments
                                payments_to_delete = db.collection('payments').where('tenant_id', '==', tenant['id']).stream()
                                for p in payments_to_delete:
                                    p.reference.delete()
                                
                                st.session_state.tenants = [t for t in st.session_state.tenants if t['id'] != tenant['id']]
                                st.session_state.payments = [p for p in st.session_state.payments if p['tenant_id'] != tenant['id']]
                            st.success(f"Tenant {tenant['name']} and all associated payments have been deleted.")
                            st.rerun()
                
                if st.session_state.get('edit_tenant_id') == tenant['id']:
                    with st.form(key=f"edit_form_{tenant['id']}"):
                        st.write(f"**Editing: {tenant['name']}**")
                        new_name = st.text_input("Name", value=tenant['name'])
                        new_property = st.text_input("Property", value=tenant['property'])
                        new_rent = st.number_input("Rent", value=tenant['rent'], format="%.2f")
                        new_deposit = st.number_input("Deposit Amount", value=tenant.get('deposit', 0.0), format="%.2f")
                        new_start_date = st.date_input("Start Date", value=datetime.strptime(tenant['start_date'], '%Y-%m-%d').date())

                        save_col, cancel_col = st.columns(2)
                        if save_col.form_submit_button("Save Changes"):
                            with st.spinner("Saving changes..."):
                                updated_data = {
                                    'name': new_name, 'property': new_property, 'rent': new_rent,
                                    'start_date': new_start_date.strftime('%Y-%m-%d'),
                                    'deposit': new_deposit
                                }
                                if db:
                                    db.collection('tenants').document(tenant['id']).update(updated_data)
                                    tenant.update(updated_data)
                                    del st.session_state.edit_tenant_id
                                    st.success("Changes saved!")
                            st.rerun()

                        if cancel_col.form_submit_button("Cancel"):
                            del st.session_state.edit_tenant_id
                            st.rerun()
                st.markdown("---")

def manage_payments():
    st.title("💵 Payment Management")
    
    if not st.session_state.get('tenants', []):
        st.warning("Please add at least one tenant before managing payments.")
        return

    with st.expander("💰 Record New Payment", expanded=True):
        with st.form("new_payment_form", clear_on_submit=True):
            tenant_options = {t['id']: f"{t['name']} ({t['property']})" for t in st.session_state.tenants}
            tenant_id = st.selectbox(
                "Select Tenant",
                options=list(tenant_options.keys()),
                format_func=lambda x: tenant_options[x],
                index=None,
                placeholder="Select a tenant..."
            )
            
            payment_date = st.date_input("Payment Date", datetime.now().date())
            amount = st.number_input("Amount Paid", min_value=0.01, format="%.2f")
            
            submitted = st.form_submit_button("Record Payment")
            if submitted and tenant_id and db:
                with st.spinner("Recording payment..."):
                    new_payment_data = {
                        'tenant_id': tenant_id,
                        'date': payment_date.strftime('%Y-%m-%d'),
                        'amount': amount
                    }
                    update_time, doc_ref = db.collection('payments').add(new_payment_data)
                    new_payment_data['id'] = doc_ref.id
                    st.session_state.payments.append(new_payment_data)
                    st.success(f"Payment of AED {amount} recorded for {tenant_options[tenant_id]}.")
                st.rerun()

    st.markdown("---")
    
    st.subheader("Monthly Payment Report")
    report_month = st.date_input("Select Month for Report", datetime.now().date(), key="report_month_selector")
    report_month_str = report_month.strftime('%Y-%m')

    all_payments = st.session_state.get('payments', [])
    payments_in_month = [
        p for p in all_payments
        if datetime.strptime(p['date'], '%Y-%m-%d').strftime('%Y-%m') == report_month_str
    ]
    
    total_collected = sum(p['amount'] for p in payments_in_month)
    st.metric(f"Total Rent Collected in {report_month.strftime('%B %Y')}", f"AED {total_collected:,.2f}")

    st.write("#### Tenants Who Paid This Month")
    
    # Group payments by tenant to handle multiple payments
    payments_by_tenant = {}
    for payment in payments_in_month:
        tenant_id = payment['tenant_id']
        if tenant_id not in payments_by_tenant:
            payments_by_tenant[tenant_id] = []
        payments_by_tenant[tenant_id].append(payment)

    if not payments_by_tenant:
        st.info("No payments were recorded for this month.")
    else:
        # Create a list of tenant info for sorting and display
        tenant_report_list = []
        for tenant_id, payments in payments_by_tenant.items():
            tenant = get_tenant_by_id(tenant_id)
            if tenant:
                tenant_report_list.append({
                    'name': tenant['name'],
                    'property': tenant['property'],
                    'payments': sorted(payments, key=lambda x: x['date']) # Sort payments by date
                })

        # Display sorted tenant list
        for tenant_info in sorted(tenant_report_list, key=lambda x: x['name']):
            total_paid_by_tenant = sum(p['amount'] for p in tenant_info['payments'])
            st.markdown(f"- **{tenant_info['name']}** ({tenant_info['property']}) - Total Paid: AED {total_paid_by_tenant:,.2f}")
            # Display each individual payment with its date
            for payment in tenant_info['payments']:
                 st.markdown(f"  - `Paid AED {payment['amount']:,.2f} on {payment['date']}`")


    st.markdown("---")
    
    st.subheader("Tenant Balances & History")
    
    tenant_options = {t['id']: f"{t['name']} ({t['property']})" for t in st.session_state.get('tenants', [])}
    if not tenant_options:
        st.info("No tenants to display.")
        return

    view_tenant_id = st.selectbox(
        "View History for Tenant",
        options=list(tenant_options.keys()),
        format_func=lambda x: tenant_options[x],
        key="view_tenant",
        index=None,
        placeholder="Select a tenant to view history..."
    )
    report_month_dt = st.date_input("View Balance for Month", datetime.now().date(), key="view_month")
    
    if view_tenant_id:
        rent_due, balance_forwarded, total_due, paid_this_month, new_balance = calculate_balance(view_tenant_id, report_month_dt)

        st.write(f"### Balance Summary for {report_month_dt.strftime('%B %Y')}")
        summary_cols = st.columns(5)
        summary_cols[0].metric("Balance Forwarded", f"AED {balance_forwarded:,.2f}")
        summary_cols[1].metric("Month's Rent", f"AED {rent_due:,.2f}")
        summary_cols[2].metric("Total Due", f"AED {total_due:,.2f}")
        summary_cols[3].metric("Paid This Month", f"AED {paid_this_month:,.2f}")
        summary_cols[4].metric("Ending Balance", f"AED {new_balance:,.2f}", delta=f"{-new_balance:,.2f}" if new_balance != 0 else "")
        
        st.markdown("---")
        st.write("#### Payment History")
        
        tenant_payments = [p for p in st.session_state.get('payments', []) if p['tenant_id'] == view_tenant_id]
        if tenant_payments:
            payments_df = pd.DataFrame(tenant_payments)
            payments_df = payments_df.sort_values(by='date', ascending=False)
            st.dataframe(payments_df[['date', 'amount']].style.format({"amount": "AED {:,.2f}"}))
        else:
            st.info("No payments recorded for this tenant yet.")

def manage_expenses():
    st.title("💸 Expense Management")

    with st.expander("📝 Add New Expense", expanded=False):
        with st.form("new_expense_form", clear_on_submit=True):
            description = st.text_input("Expense Description (e.g., 'Plumbing Repair')")
            amount = st.number_input("Amount", min_value=0.01, format="%.2f")
            expense_date = st.date_input("Date of Expense", datetime.now().date())

            submitted = st.form_submit_button("Add Expense")
            if submitted and description and amount > 0 and db:
                with st.spinner("Adding expense..."):
                    new_expense_data = {
                        'description': description,
                        'amount': amount,
                        'date': expense_date.strftime('%Y-%m-%d')
                    }
                    update_time, doc_ref = db.collection('expenses').add(new_expense_data)
                    new_expense_data['id'] = doc_ref.id
                    st.session_state.expenses.append(new_expense_data)
                    st.success(f"Expense '{description}' of AED {amount} added.")
                st.rerun()

    st.markdown("---")

    st.subheader("Expense History")
    if not st.session_state.get('expenses', []):
        st.info("No expenses recorded yet.")
    else:
        expenses_df = pd.DataFrame(st.session_state.get('expenses', []))
        expenses_df = expenses_df.sort_values(by='date', ascending=False)
        
        expenses_df['delete'] = False
        edited_df = st.data_editor(
            expenses_df,
            column_config={"delete": st.column_config.CheckboxColumn("Delete?", default=False)},
            disabled=["id", "description", "amount", "date"], hide_index=True,
        )

        expenses_to_delete = edited_df[edited_df['delete']].id.tolist()
        if expenses_to_delete and db:
            with st.spinner("Deleting expense(s)..."):
                for doc_id in expenses_to_delete:
                    db.collection('expenses').document(doc_id).delete()
                
                st.session_state.expenses = [exp for exp in st.session_state.expenses if exp['id'] not in expenses_to_delete]
                st.warning("Expense(s) deleted. Rerunning...")
            st.rerun()


# --- AUTHENTICATION AND APP LOGIC ---
def show_login_form():
    """Displays the login form."""
    # Custom CSS for rounded corners on the image
    st.markdown("""
        <style>
            .login-img img {
                border-radius: 15px;
            }
        </style>
    """, unsafe_allow_html=True)
    
    # Use columns to center the form and make it smaller
    col1, col2, col3 = st.columns([1, 1, 1])

    with col2:
        # Wrap image in a div to apply the class
        st.markdown('<div class="login-img">', unsafe_allow_html=True)
        st.image("logo.jpg", use_container_width=True)
        st.markdown('</div>', unsafe_allow_html=True)
        
        st.markdown("<h1 style='text-align: center;'>Beth Room Rental</h1>", unsafe_allow_html=True)
        st.markdown("<h3 style='text-align: center;'>Admin Login</h3>", unsafe_allow_html=True)
        
        with st.form("login_form"):
            username = st.text_input("Username")
            password = st.text_input("Password", type="password")
            submitted = st.form_submit_button("Login")
            
            if submitted:
                try:
                    admin_user = st.secrets["admin_credentials"]["username"]
                    admin_pass = st.secrets["admin_credentials"]["password"]
                    
                    if username == admin_user and password == admin_pass:
                        st.session_state.authenticated = True
                        st.rerun() # Re-added to fix the "double enter" bug by forcing an immediate script rerun.
                    else:
                        st.error("The username or password you entered is incorrect.")
                except Exception as e:
                    st.error("Admin credentials are not configured correctly in secrets.toml.")
                    st.error(e)

def show_main_app():
    """Shows the main application pages after successful login."""
    if db:
        load_data_from_firestore()

        st.sidebar.title("Navigation")
        # Add logout button to sidebar
        if st.sidebar.button("Logout"):
            st.session_state.authenticated = False
            st.rerun()
            
        selection = st.sidebar.radio("Go to", ["Dashboard", "Tenant Management", "Payment Management", "Expense Management"])

        if selection == "Dashboard":
            show_dashboard()
        elif selection == "Tenant Management":
            manage_tenants()
        elif selection == "Payment Management":
            manage_payments()
        elif selection == "Expense Management":
            manage_expenses()

def main():
    """Main function to handle app flow based on authentication."""
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False

    if st.session_state.authenticated:
        show_main_app()
    else:
        show_login_form()

if __name__ == "__main__":
    main()

